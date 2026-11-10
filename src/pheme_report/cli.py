"""Command line: ``pheme-report build``, ``verify`` and ``serve``."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .ai import DEFAULT_MODEL, BedrockAnalyst
from .build import DEFAULT_OUTCOME_RULES, build_report, content_equal, load_report, verify_report, write_report

DEFAULT_OUT = "out"
DEFAULT_REPORT = "report/execution_report.json"


def load_dotenv(path: Path) -> None:
    """Read ``KEY=value`` lines from ``.env``. Variables already set in the shell win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def make_analyst() -> BedrockAnalyst:
    return BedrockAnalyst(
        model=os.environ.get("PHEME_MODEL") or DEFAULT_MODEL,
        region=os.environ.get("PHEME_AWS_REGION") or None,
        profile=os.environ.get("PHEME_AWS_PROFILE") or None,
        api_key=os.environ.get("PHEME_BEDROCK_API_KEY") or None,
        effort=os.environ.get("PHEME_EFFORT") or "medium",
    )


def outcome_rules() -> dict[str, list[str]]:
    """Pass/fail verdict lists: PHEME_PASS_VERDICTS / PHEME_FAIL_VERDICTS, else the defaults."""

    def labels(name: str, default: list[str]) -> list[str]:
        raw = os.environ.get(name, "")
        found = [v.strip().upper() for v in raw.split(",") if v.strip()]
        return found or default

    return {
        "pass": labels("PHEME_PASS_VERDICTS", DEFAULT_OUTCOME_RULES["pass"]),
        "fail": labels("PHEME_FAIL_VERDICTS", DEFAULT_OUTCOME_RULES["fail"]),
    }


def _summary(report: dict) -> str:
    s = report["summary"]
    runs = report["runs"]
    ai_ok = sum(1 for r in runs if r["ai"].get("status") == "ok")
    return (
        f"{s['runs_total']} run(s), {s['cases_executed']} case(s): {s['passed']} passed, "
        f"{s['failed']} failed, {s['other']} other; AI analysis on {ai_ok} of {len(runs)} run(s)"
    )


def cmd_build(args: argparse.Namespace) -> int:
    out_dir, report_path = Path(args.out), Path(args.report)
    if not out_dir.is_dir():
        print(f"error: {out_dir} is not a directory", file=sys.stderr)
        return 2

    def once() -> int:
        previous = load_report(report_path)
        report = build_report(
            out_dir,
            previous,
            None if args.no_ai else make_analyst,
            rules=outcome_rules(),
            force_ai=args.force_ai,
            log=print,
        )
        if content_equal(previous, report):
            if not args.watch:
                print(f"No change: {report_path} is up to date ({_summary(report)}).")
            return 0
        write_report(report_path, report)
        print(f"Wrote {report_path}: {_summary(report)}.")
        failed = [r["stamp"] for r in report["runs"] if r["ai"].get("status") == "error"]
        if failed:
            print(
                f"AI analysis failed for {', '.join(failed)}; the facts are in the report "
                "and the analysis is retried on the next build.",
                file=sys.stderr,
            )
            return 1
        return 0

    if not args.watch:
        return once()
    print(f"Watching {out_dir} every {args.watch}s. Ctrl+C to stop.")
    try:
        while True:
            once()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


def cmd_verify(args: argparse.Namespace) -> int:
    report = load_report(Path(args.report))
    if report is None:
        print(f"error: no readable report at {args.report}", file=sys.stderr)
        return 2
    problems = verify_report(Path(args.out), report)
    for problem in problems:
        print(f"MISMATCH  {problem}")
    if problems:
        return 1
    print(f"OK: every fact in {args.report} matches the log files ({_summary(report)}).")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    try:
        server = serve(Path(args.report), make_analyst, args.port)
    except OSError as exc:
        print(f"error: cannot listen on port {args.port}: {exc}", file=sys.stderr)
        return 2
    print(f"Answering questions about {args.report} on http://127.0.0.1:{args.port}. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pheme-report", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out", default=DEFAULT_OUT, help="folder with the execution logs")
        p.add_argument("--report", default=DEFAULT_REPORT, help="consolidated JSON report")

    build = sub.add_parser("build", help="create or update the consolidated report")
    common(build)
    build.add_argument("--no-ai", action="store_true", help="parse only, no Bedrock call")
    build.add_argument("--force-ai", action="store_true", help="redo the AI analysis of every run")
    build.add_argument(
        "--watch",
        type=int,
        nargs="?",
        const=30,
        default=0,
        metavar="SECONDS",
        help="keep running and update the report when new logs appear (default every 30s)",
    )
    build.set_defaults(func=cmd_build)

    verify = sub.add_parser("verify", help="check the report's facts against the log files")
    common(verify)
    verify.set_defaults(func=cmd_verify)

    ask = sub.add_parser("serve", help="answer the dashboard's questions about the report")
    ask.add_argument("--report", default=DEFAULT_REPORT, help="consolidated JSON report")
    ask.add_argument("--port", type=int, default=8787, help="local port (default 8787)")
    ask.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    load_dotenv(Path(".env"))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
