"""Builds and updates the consolidated report.

Each run in the report has three separate layers, so a reader can always tell where a value
came from:

``facts``     copied from the files under ``out/`` by :mod:`pheme_report.parse`
``computed``  counts, pass/fail totals and averages calculated from the facts by this module
``ai``        commentary written by the Bedrock model; never an input to the other two

The top-level ``ai_analytics`` section holds the model commentary that spans runs (why a
verdict changed, what a flaky case's flipping looks like) and counts taken over the model's
cause labels. Like ``ai``, it is never an input to ``facts``, ``computed``, ``summary`` or
``trend``.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import SCHEMA_VERSION
from .ai import (
    LIKELY_CAUSES,
    Analyst,
    AnalystError,
    analyze_changes,
    analyze_flaky,
    analyze_run,
    analyze_trend,
)
from .parse import canonical_sha256, discover_stamps, parse_run

NO_VERDICT = "(no verdict)"
# A case is flaky when its pass/fail outcome changed at least this many times across runs.
FLAKY_MIN_FLIPS = 2
# Verdict changes into the latest runs get a model explanation; older ones keep theirs.
EXPLAIN_CHANGES_IN_LATEST_RUNS = 5
# Runs of a flaky case shown to the model, newest last.
FLAKY_RUNS_SHOWN = 6

# Which verdict labels count as passed and which as failed (compared without regard to case).
# A verdict in neither list is counted as "other". The lists in use are written to the report.
DEFAULT_OUTCOME_RULES: dict[str, list[str]] = {
    "pass": ["PASS", "PASSED", "MATCH", "EXACT", "OK", "CLOSE"],
    "fail": ["MISMATCH", "FAIL", "FAILED", "ERROR", "TIMEOUT"],
}


def outcome_of(verdict: str | None, rules: dict[str, list[str]]) -> str:
    """"pass", "fail" or "other" for a verdict label. The label itself is never changed."""
    label = (verdict or "").strip().upper()
    if label in {v.upper() for v in rules["pass"]}:
        return "pass"
    if label in {v.upper() for v in rules["fail"]}:
        return "fail"
    return "other"


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total * 100, 1) if total else None
POLICY = (
    "facts are copied from the log files by a deterministic parser; computed values and "
    "summary are arithmetic over the facts, with pass/fail decided by outcome_rules; ai is model commentary and is never written into facts or "
    "computed."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stats(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "avg": round(sum(values) / len(values), 1),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def _duration_s(execution: Any) -> float | None:
    if not isinstance(execution, dict):
        return None
    try:
        started = datetime.fromisoformat(execution["started"])
        finished = datetime.fromisoformat(execution["finished"])
    except (KeyError, TypeError, ValueError):
        return None
    return (finished - started).total_seconds()


def compute(facts: dict[str, Any], rules: dict[str, list[str]]) -> dict[str, Any]:
    """Totals and averages for one run, plus notes where the files disagree with each other."""
    cases = facts["cases"]
    case_outcomes = {c["case_id"]: outcome_of(c["assertion"]["verdict"], rules) for c in cases}
    tally = {"pass": 0, "fail": 0, "other": 0}
    for outcome in case_outcomes.values():
        tally[outcome] += 1
    execution = facts["execution"] if isinstance(facts["execution"], dict) else {}

    verdict_counts: dict[str, int] = {}
    dlt_by_level: dict[str, int] = {}
    for case in cases:
        verdict = case["assertion"]["verdict"] or NO_VERDICT
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        if case["dlt"]:
            for level, n in case["dlt"]["by_level"].items():
                dlt_by_level[level] = dlt_by_level.get(level, 0) + n

    def numbers(field: str) -> list[float]:
        return [
            c["assertion"][field]
            for c in cases
            if isinstance(c["assertion"].get(field), (int, float))
        ]

    metrics = {
        "cases_total": len(cases),
        "cases_selected": execution.get("selected") if isinstance(execution.get("selected"), int) else None,
        "cases_completed": execution.get("completed") if isinstance(execution.get("completed"), int) else None,
        "passed": tally["pass"],
        "failed": tally["fail"],
        "other": tally["other"],
        "pass_rate_pct": _rate(tally["pass"], len(cases)),
        "verdict_counts": verdict_counts,
        "latency_ms": _stats(numbers("latency_ms")),
        "similarity_pct": _stats(numbers("similarity_pct")),
        "cases_with_telemetry_errors": sum(1 for c in cases if c["telemetry_errors"]),
        "cases_with_flags": sum(1 for c in cases if c["flags"]),
        "dlt_messages_by_level": dlt_by_level,
        "duration_s": _duration_s(execution),
    }

    consistency: list[str] = []
    if facts["execution"] is None:
        consistency.append("No execution_<stamp>.json file was found for this run.")
    completed = execution.get("completed")
    if isinstance(completed, int) and completed != len(cases):
        consistency.append(
            f"execution.completed is {completed} but {len(cases)} case logs were found."
        )
    for case in cases:
        declared = case["timeline"]["declared_events"]
        found = len(case["timeline"]["events"])
        if declared is not None and declared != found:
            consistency.append(
                f"{case['case_id']}: the timeline header says {declared} events, {found} are listed."
            )
        if execution.get("dlt_capture") is True and case["dlt"] is None:
            consistency.append(f"{case['case_id']}: DLT capture was on but no DLT file was found.")

    return {"metrics": metrics, "case_outcomes": case_outcomes, "consistency": consistency}


# --------------------------------------------------------------------------- trend


def build_trend(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """One data point per run, every case whose verdict changed, and a summary of the direction.

    Works for any number of runs: with a single run the point is the baseline and the summary
    says so; comparisons start with the second run.
    """
    points = []
    history: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        execution = run["facts"]["execution"] if isinstance(run["facts"]["execution"], dict) else {}
        m = run["computed"]["metrics"]
        points.append(
            {
                "stamp": run["stamp"],
                "started": execution.get("started"),
                "sheet": execution.get("sheet"),
                "outcome": execution.get("outcome"),
                "cases_total": m["cases_total"],
                "cases_selected": m["cases_selected"],
                "cases_completed": m["cases_completed"],
                "passed": m["passed"],
                "failed": m["failed"],
                "other": m["other"],
                "pass_rate_pct": m["pass_rate_pct"],
                "verdict_counts": m["verdict_counts"],
                "avg_latency_ms": m["latency_ms"]["avg"] if m["latency_ms"] else None,
                "avg_similarity_pct": m["similarity_pct"]["avg"] if m["similarity_pct"] else None,
                "cases_with_telemetry_errors": m["cases_with_telemetry_errors"],
                "cases_with_flags": m["cases_with_flags"],
                "duration_s": m["duration_s"],
            }
        )
        for case in run["facts"]["cases"]:
            history.setdefault(case["key"], []).append(
                {
                    "stamp": run["stamp"],
                    "case_id": case["case_id"],
                    "verdict": case["assertion"]["verdict"],
                    "outcome": run["computed"]["case_outcomes"][case["case_id"]],
                    "similarity_pct": case["assertion"]["similarity_pct"],
                    "latency_ms": case["assertion"]["latency_ms"],
                }
            )

    changes = []
    for key, entries in history.items():
        for before, after in zip(entries, entries[1:]):
            if before["verdict"] != after["verdict"]:
                changes.append(
                    {
                        "case_key": key,
                        "from_stamp": before["stamp"],
                        "to_stamp": after["stamp"],
                        "from_verdict": before["verdict"],
                        "to_verdict": after["verdict"],
                        "from_outcome": before["outcome"],
                        "to_outcome": after["outcome"],
                    }
                )
    changes.sort(key=lambda c: (c["to_stamp"], c["case_key"]))

    flaky = []
    failing_streaks: dict[str, int] = {}
    for key, entries in history.items():
        outcomes = [e["outcome"] for e in entries]
        flips = sum(1 for a, b in zip(outcomes, outcomes[1:]) if a != b)
        if flips >= FLAKY_MIN_FLIPS:
            flaky.append(
                {
                    "case_key": key,
                    "runs": len(entries),
                    "flips": flips,
                    "passed": outcomes.count("pass"),
                    "failed": outcomes.count("fail"),
                    "other": outcomes.count("other"),
                    "latest_outcome": outcomes[-1],
                }
            )
        streak = 0
        for outcome in reversed(outcomes):
            if outcome != "fail":
                break
            streak += 1
        if streak:
            failing_streaks[key] = streak
    flaky.sort(key=lambda f: (-f["flips"], f["case_key"]))

    return {
        "summary": _trend_summary(points, changes),
        "points": points,
        "case_history": history,
        "changes": changes,
        "flaky_cases": flaky,
        "failing_streaks": failing_streaks,
    }


def _trend_summary(points: list[dict[str, Any]], changes: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "runs": len(points),
        "status": "no_runs",
        "note": "No runs recorded yet.",
        "latest_stamp": points[-1]["stamp"] if points else None,
        "previous_stamp": points[-2]["stamp"] if len(points) > 1 else None,
        "direction": None,
        "pass_rate_change_pts": None,
        "passed_change": None,
        "failed_change": None,
        "newly_failing": [],
        "newly_passing": [],
    }
    if len(points) == 1:
        summary["status"] = "single_run"
        summary["note"] = "One run recorded. It is the baseline; comparisons start with the next run."
    elif len(points) > 1:
        latest, previous = points[-1], points[-2]
        summary["status"] = "ok"
        summary["note"] = f"Latest run compared with the run before it ({previous['stamp']})."
        summary["passed_change"] = latest["passed"] - previous["passed"]
        summary["failed_change"] = latest["failed"] - previous["failed"]
        if latest["pass_rate_pct"] is not None and previous["pass_rate_pct"] is not None:
            change = round(latest["pass_rate_pct"] - previous["pass_rate_pct"], 1)
            summary["pass_rate_change_pts"] = change
            summary["direction"] = "improving" if change > 0 else "declining" if change < 0 else "stable"
        for c in changes:
            if c["to_stamp"] != latest["stamp"] or c["from_outcome"] == c["to_outcome"]:
                continue
            if c["to_outcome"] == "fail":
                summary["newly_failing"].append(c["case_key"])
            elif c["to_outcome"] == "pass":
                summary["newly_passing"].append(c["case_key"])
    return summary


def build_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals across every run in the report, and the latest run on its own."""

    def total(field: str) -> int:
        return sum(r["computed"]["metrics"][field] or 0 for r in runs)

    def outcome(run: dict[str, Any]) -> Any:
        execution = run["facts"]["execution"]
        return execution.get("outcome") if isinstance(execution, dict) else None

    executed = total("cases_total")
    latest = None
    if runs:
        m = runs[-1]["computed"]["metrics"]
        latest = {
            "stamp": runs[-1]["stamp"],
            "outcome": outcome(runs[-1]),
            "cases_selected": m["cases_selected"],
            "cases_completed": m["cases_completed"],
            "cases_executed": m["cases_total"],
            "passed": m["passed"],
            "failed": m["failed"],
            "other": m["other"],
            "pass_rate_pct": m["pass_rate_pct"],
        }
    return {
        "runs_total": len(runs),
        "runs_completed": sum(1 for r in runs if outcome(r) == "completed"),
        "cases_selected": total("cases_selected"),
        "cases_completed": total("cases_completed"),
        "cases_executed": executed,
        "passed": total("passed"),
        "failed": total("failed"),
        "other": total("other"),
        "pass_rate_pct": _rate(total("passed"), executed),
        "latest": latest,
    }


# -------------------------------------------------------------------------- report


def load_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        return None
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Write atomically, so a dashboard polling the file never reads half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".report-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _ai_usable(ai: Any, input_sha: str) -> bool:
    return isinstance(ai, dict) and ai.get("status") == "ok" and ai.get("input_sha256") == input_sha


def change_id(change: dict[str, Any]) -> str:
    return f"{change['case_key']} @ {change['from_stamp']}>{change['to_stamp']}"


def causes_by_run(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per run: how many failed cases the model put under each likely cause."""
    out = []
    for run in runs:
        analyses = run["ai"].get("cases") if run["ai"].get("status") == "ok" else None
        failed = [cid for cid, o in run["computed"]["case_outcomes"].items() if o == "fail"]
        counts: dict[str, int] = {}
        for case_id in failed:
            cause = (analyses or {}).get(case_id, {}).get("likely_cause")
            if cause:
                counts[cause] = counts.get(cause, 0) + 1
        out.append(
            {
                "stamp": run["stamp"],
                "analysed": analyses is not None,
                "failed_cases": len(failed),
                "failed_by_cause": {c: counts[c] for c in LIKELY_CAUSES if c in counts},
            }
        )
    return out


def build_report(
    out_dir: Path,
    previous: dict[str, Any] | None,
    analyst_factory: Callable[[], Analyst] | None,
    *,
    rules: dict[str, list[str]] | None = None,
    force_ai: bool = False,
    log: Callable[[str], None] = lambda _msg: None,
) -> dict[str, Any]:
    """Parse ``out_dir``, merge with the previous report and return the new report.

    ``analyst_factory`` is called at most once, and only if a run needs model commentary;
    pass ``None`` to build without the model.
    """
    rules = rules or DEFAULT_OUTCOME_RULES
    prev_runs = {r["stamp"]: r for r in (previous or {}).get("runs", [])}
    analyst: Analyst | None = None
    analyst_error: str | None = None

    def get_analyst() -> Analyst | None:
        nonlocal analyst, analyst_error
        if analyst is None and analyst_error is None and analyst_factory is not None:
            try:
                analyst = analyst_factory()
            except Exception as exc:  # missing credentials, bad model id, SDK not installed
                analyst_error = f"{type(exc).__name__}: {exc}"
        return analyst

    runs: list[dict[str, Any]] = []
    stamps = discover_stamps(out_dir)
    for stamp in stamps:
        parsed = parse_run(out_dir, stamp)
        facts = parsed["facts"]
        facts_sha = canonical_sha256(facts)
        computed = compute(facts, rules)
        # The commentary was written for these facts and these pass/fail rules.
        input_sha = canonical_sha256({"facts": facts_sha, "rules": rules})
        prev_ai = prev_runs.get(stamp, {}).get("ai")

        if isinstance(prev_ai, dict) and "failure_groups" not in prev_ai:
            prev_ai = None  # written before failure groups existed; analyse again

        if _ai_usable(prev_ai, input_sha) and not force_ai:
            ai = prev_ai
        elif analyst_factory is None:
            # Commentary written for different facts must not be shown against these.
            ai = prev_ai if _ai_usable(prev_ai, input_sha) else {
                "status": "skipped",
                "reason": "built with --no-ai",
            }
        elif not facts["cases"]:
            ai = {"status": "skipped", "reason": "the run has no case logs"}
        elif facts["execution"] is None:
            # The harness writes this file when the run ends; analyse once it is there.
            ai = {
                "status": "skipped",
                "reason": f"waiting for execution_{stamp}.json (the run may still be in progress)",
            }
        else:
            current = get_analyst()
            if current is None:
                ai = {"status": "error", "error": analyst_error}
                log(f"  {stamp}: AI analysis unavailable ({analyst_error})")
            else:
                log(f"  {stamp}: analysing {len(facts['cases'])} cases with {current.model}")
                try:
                    ai = {
                        "status": "ok",
                        "model": current.model,
                        "generated_at": _now(),
                        "input_sha256": input_sha,
                        **analyze_run(current, facts, computed),
                    }
                except AnalystError as exc:
                    ai = {"status": "error", "model": current.model, "error": str(exc)}
                    log(f"  {stamp}: AI analysis failed ({exc})")

        runs.append(
            {
                "stamp": stamp,
                "source_present": True,
                "facts": facts,
                "facts_sha256": facts_sha,
                "computed": computed,
                "sources": parsed["sources"],
                "parse_warnings": parsed["parse_warnings"],
                "ai": ai,
            }
        )

    # Runs whose logs have since been removed from out/ stay in the report as history.
    for stamp, run in prev_runs.items():
        if stamp not in stamps:
            runs.append({**run, "computed": compute(run["facts"], rules), "source_present": False})
    runs.sort(key=lambda r: r["stamp"])

    trend = build_trend(runs)
    trend_sha = canonical_sha256({"points": trend["points"], "changes": trend["changes"]})
    prev_trend_ai = (previous or {}).get("ai_trend")
    if len(runs) < 2:
        ai_trend: dict[str, Any] = {"status": "skipped", "reason": "a trend needs at least two runs"}
    elif _ai_usable(prev_trend_ai, trend_sha) and not force_ai:
        ai_trend = prev_trend_ai
    elif analyst_factory is None:
        ai_trend = {"status": "skipped", "reason": "built with --no-ai"}
    else:
        current = get_analyst()
        if current is None:
            ai_trend = {"status": "error", "error": analyst_error}
        else:
            log(f"  trend: analysing {len(runs)} runs with {current.model}")
            try:
                ai_trend = {
                    "status": "ok",
                    "model": current.model,
                    "generated_at": _now(),
                    "input_sha256": trend_sha,
                    **analyze_trend(current, trend),
                }
            except AnalystError as exc:
                ai_trend = {"status": "error", "model": current.model, "error": str(exc)}
                log(f"  trend: AI analysis failed ({exc})")

    # ---- commentary that spans runs: one cached item per verdict change / flaky case ----

    def item_section(
        label: str,
        wanted: list[dict[str, Any]],
        payloads: dict[str, dict[str, Any]],
        previous_items: list[dict[str, Any]],
        analyze: Callable[[Analyst, list[dict[str, Any]]], dict[str, dict[str, Any]]],
        empty_reason: str,
    ) -> dict[str, Any]:
        """Reuse the items whose input is unchanged, ask the model for the rest."""
        if not wanted:
            return {"status": "skipped", "reason": empty_reason, "items": []}
        kept = {
            i["id"]: i
            for i in previous_items
            if isinstance(i, dict) and "id" in i and not force_ai
        }
        items: dict[str, dict[str, Any]] = {}
        missing = []
        for head in wanted:
            old = kept.get(head["id"])
            if old and old.get("input_sha256") == head["input_sha256"]:
                items[head["id"]] = old
            else:
                missing.append(head)
        section: dict[str, Any] = {"status": "ok"}
        if missing and analyst_factory is None:
            section = {"status": "skipped", "reason": "built with --no-ai"}
        elif missing:
            current = get_analyst()
            if current is None:
                section = {"status": "error", "error": analyst_error}
            else:
                log(f"  {label}: analysing {len(missing)} with {current.model}")
                try:
                    answers = analyze(current, [payloads[h["id"]] for h in missing])
                    stamp_now = _now()
                    for head in missing:
                        if head["id"] in answers:
                            items[head["id"]] = {
                                **head,
                                "model": current.model,
                                "generated_at": stamp_now,
                                **answers[head["id"]],
                            }
                except AnalystError as exc:
                    section = {"status": "error", "model": current.model, "error": str(exc)}
                    log(f"  {label}: AI analysis failed ({exc})")
        section["items"] = [items[h["id"]] for h in wanted if h["id"] in items]
        return section

    case_by_id = {c["case_id"]: c for r in runs for c in r["facts"]["cases"]}
    prev_analytics = (previous or {}).get("ai_analytics") or {}

    recent = {r["stamp"] for r in runs[-EXPLAIN_CHANGES_IN_LATEST_RUNS:]}
    change_heads, change_payloads = [], {}
    for change in trend["changes"]:
        if change["to_stamp"] not in recent:
            continue
        entries = {e["stamp"]: e for e in trend["case_history"][change["case_key"]]}
        before = case_by_id[entries[change["from_stamp"]]["case_id"]]
        after = case_by_id[entries[change["to_stamp"]]["case_id"]]
        cid = change_id(change)
        change_heads.append(
            {"id": cid, **change, "input_sha256": canonical_sha256([before, after])}
        )
        change_payloads[cid] = {"change_id": cid, **change, "before": before, "after": after}
    # Explanations of older changes stay as they are.
    older = [
        i
        for i in (prev_analytics.get("changes") or {}).get("items", [])
        if isinstance(i, dict) and i.get("to_stamp") not in recent and any(
            change_id(c) == i.get("id") for c in trend["changes"]
        )
    ]
    ai_changes = item_section(
        "verdict changes",
        change_heads,
        change_payloads,
        (prev_analytics.get("changes") or {}).get("items", []),
        lambda a, payload: analyze_changes(a, payload),
        "no verdict changed between the latest runs",
    )
    ai_changes["items"] = older + ai_changes["items"]

    flaky_heads, flaky_payloads = [], {}
    for flaky in trend["flaky_cases"]:
        key = flaky["case_key"]
        shown = trend["case_history"][key][-FLAKY_RUNS_SHOWN:]
        results = [
            {"stamp": e["stamp"], "counted_as": e["outcome"], "result": case_by_id[e["case_id"]]}
            for e in shown
        ]
        flaky_heads.append({"id": key, "case_key": key, "input_sha256": canonical_sha256(results)})
        flaky_payloads[key] = {"case_key": key, "runs": results}
    ai_flaky = item_section(
        "flaky cases",
        flaky_heads,
        flaky_payloads,
        (prev_analytics.get("flaky") or {}).get("items", []),
        lambda a, payload: analyze_flaky(a, payload),
        "no case flipped between pass and fail often enough to count as flaky",
    )

    now = _now()
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": (previous or {}).get("created_at", now),
        "updated_at": now,
        "policy": POLICY,
        "outcome_rules": rules,
        "summary": build_summary(runs),
        "runs": runs,
        "trend": trend,
        "ai_trend": ai_trend,
        "ai_analytics": {
            "causes_by_run": causes_by_run(runs),
            "changes": ai_changes,
            "flaky": ai_flaky,
        },
    }


def content_equal(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    """True when two reports differ only in ``updated_at``."""
    if a is None:
        return False
    strip = lambda r: {k: v for k, v in r.items() if k != "updated_at"}  # noqa: E731
    return strip(a) == strip(b)


def verify_report(out_dir: Path, report: dict[str, Any]) -> list[str]:
    """Re-parse the logs and compare with the report's facts. Returns the problems found."""
    problems: list[str] = []
    rules = report.get("outcome_rules") or DEFAULT_OUTCOME_RULES
    if build_summary(report.get("runs", [])) != report.get("summary"):
        problems.append("summary: does not follow from the runs in the report.")
    for run in report.get("runs", []):
        stamp = run["stamp"]
        if canonical_sha256(run["facts"]) != run["facts_sha256"]:
            problems.append(f"{stamp}: facts in the report do not match their recorded hash.")
        if compute(run["facts"], rules) != run["computed"]:
            problems.append(f"{stamp}: computed values do not follow from the facts.")
        if stamp not in discover_stamps(out_dir):
            continue  # logs removed since; nothing to compare against
        parsed = parse_run(out_dir, stamp)
        if parsed["facts"] != run["facts"]:
            problems.append(f"{stamp}: facts in the report differ from the log files.")
        if parsed["sources"] != run["sources"]:
            problems.append(f"{stamp}: log files changed since the report was built.")
    if build_trend(report.get("runs", [])) != report.get("trend"):
        problems.append("trend: does not follow from the runs in the report.")
    return problems
