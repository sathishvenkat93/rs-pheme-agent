from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

import threading
import urllib.error
import urllib.request

from pheme_report.ai import (
    CASE_SCHEMA,
    CHANGE_SCHEMA,
    FLAKY_SCHEMA,
    GROUP_SCHEMA,
    SUMMARY_SCHEMA,
    TREND_SCHEMA,
    AnalystError,
)
from pheme_report.build import build_report, content_equal, verify_report, write_report
from pheme_report.parse import parse_run
from pheme_report.qa import QA_SCHEMA, answer_question, report_digest
from pheme_report.server import serve

FIXTURES = Path(__file__).parent / "fixtures" / "out"
STAMP = "20261110_120000"
STAMP_2 = "20261111_090000"
STAMP_3 = "20261112_090000"
ROW_4 = "VDC - Error | row 4 | Close the rear window"
CASE_3 = f"{STAMP}/VDC-Error_0003_Open_passenger_window"
CASE_4 = f"{STAMP}/VDC-Error_0004_Close_rear_window"


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "out"
    shutil.copytree(FIXTURES, dest)
    return dest


def add_run(out_dir: Path, stamp: str, *, fixed: bool) -> None:
    """A later run of the same two cases. With ``fixed`` the rear-window case reads CLOSE."""
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and STAMP in path.as_posix():
            target = Path(path.as_posix().replace(STAMP, stamp))
            target.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text().replace(STAMP, stamp).replace("2026-11-10", f"2026-11-{stamp[6:8]}")
            if fixed and path.name == "VDC-Error_0004_Close_rear_window.log":
                text = text.replace(
                    "actual       : The rear window is open", "actual       : The rear window is closed."
                ).replace(
                    "verdict      : MISMATCH  (similarity 82.4%)  <-- conflicting terms: ['closed'] vs ['open']",
                    "verdict      : CLOSE  (similarity 98.0%)",
                ).replace("latency      : 2060 ms", "latency      : 1500 ms")
            target.write_text(text)


def add_second_run(out_dir: Path) -> None:
    add_run(out_dir, STAMP_2, fixed=True)


class FakeAnalyst:
    """Answers like the model would, and also tries to overwrite results."""

    model = "anthropic.fake"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ask(self, task, payload, schema):
        self.calls.append(schema)
        usage = {"input_tokens": 10, "output_tokens": 5}
        if schema is CASE_SCHEMA:
            cases = [
                {
                    "case_id": c["case_id"],
                    "likely_cause": "incorrect_response",
                    "explanation": "The spoken text differs from the expected text.",
                    "evidence": [
                        f"actual       : {c['assertion']['actual']}",  # in the log
                        "this sentence appears in no log",  # invented
                    ],
                    "suggested_action": "Check the response mapping.",
                    "confidence": "medium",
                    # Not part of the schema: an attempt to change the result.
                    "verdict": "PASS",
                    "assertion": {"verdict": "PASS", "actual": "rewritten"},
                }
                for c in payload["cases"]
            ]
            cases.append({"case_id": "does/not/exist", "likely_cause": "none", "explanation": "x",
                          "evidence": [], "suggested_action": "", "confidence": "high"})
            return {"cases": cases}, usage
        if schema is SUMMARY_SCHEMA:
            return {
                "headline": "One mismatch",
                "overview": "Two cases ran.",
                "key_findings": ["finding"],
                "recommended_actions": ["action"],
                "metrics": {"cases_total": 999},
            }, usage
        if schema is GROUP_SCHEMA:
            ids = [c["case_id"] for c in payload["failed_cases"]]
            return {
                "groups": [
                    {
                        "title": "Resolver error",
                        "likely_cause": "system_under_test_error",
                        "description": "Same failing step.",
                        "case_ids": ids + ["does/not/exist"],
                        "shared_evidence": ['Step execution failed: Interpret("Unavailable")', "made up"],
                        "suggested_action": "Check the resolver.",
                        "verdict": "PASS",
                    },
                    # The same cases again, and a group of unknown cases: both must go.
                    {"title": "Duplicate", "likely_cause": "none", "description": "", "case_ids": ids,
                     "shared_evidence": [], "suggested_action": ""},
                    {"title": "Ghost", "likely_cause": "none", "description": "", "case_ids": ["nope"],
                     "shared_evidence": [], "suggested_action": ""},
                ]
            }, usage
        if schema is CHANGE_SCHEMA:
            return {
                "changes": [
                    {
                        "change_id": c["change_id"],
                        "explanation": f"{c['from_verdict']} became {c['to_verdict']}.",
                        "differences": ["The spoken text changed."],
                        "evidence_before": [f"actual       : {c['before']['assertion']['actual']}", "made up"],
                        "evidence_after": [f"actual       : {c['after']['assertion']['actual']}"],
                        "confidence": "high",
                        "to_verdict": "PASS",
                    }
                    for c in payload["changes"]
                ]
                + [{"change_id": "unknown", "explanation": "x", "differences": [], "evidence_before": [],
                    "evidence_after": [], "confidence": "low"}]
            }, usage
        if schema is FLAKY_SCHEMA:
            return {
                "cases": [
                    {
                        "case_key": c["case_key"],
                        "pattern": "system_instability",
                        "explanation": "The resolver error comes and goes.",
                        "evidence": ['Step execution failed: Interpret("Unavailable")', "made up"],
                        "suggested_action": "Watch the resolver.",
                        "confidence": "medium",
                    }
                    for c in payload["cases"]
                ]
            }, usage
        assert schema is TREND_SCHEMA
        return {"headline": "Improved", "narrative": "n", "notable_changes": ["c"]}, usage

    def converse(self, system, messages, schema):
        self.calls.append(schema)
        assert schema is QA_SCHEMA
        self.last_system, self.last_messages = system, messages
        return {
            "answer": f"Answer to: {messages[-1]['content']}",
            "referenced_case_ids": [CASE_4, "does/not/exist", CASE_4],
            "summary": {"passed": 999},
        }, {"input_tokens": 1, "output_tokens": 1}


# ------------------------------------------------------------------------------ parsing


def test_facts_are_copied_from_the_logs(out_dir: Path) -> None:
    parsed = parse_run(out_dir, STAMP)
    facts = parsed["facts"]

    assert facts["execution"] == json.loads((out_dir / f"execution_{STAMP}.json").read_text())
    assert facts["baseline"] == json.loads((out_dir / f"vui_baseline_{STAMP}.json").read_text())
    assert parsed["parse_warnings"] == []
    assert len(parsed["sources"]) == 8

    c3, c4 = facts["cases"]
    assert (c3["case_id"], c4["case_id"]) == (CASE_3, CASE_4)
    assert (c3["sheet"], c3["excel_row"], c3["category"]) == ("VDC - Error", 3, "VCB - Body")
    assert c3["utterance"] == "Open the passenger window"
    assert c3["assertion"] == {
        "expected": "This function is not available",
        "actual": "That function is not available",
        "verdict": "CLOSE",
        "similarity_pct": 91.3,
        "latency_ms": 1820,
    }
    assert c3["stimulus"]["applied"] == (
        "FUNC=40 0 0 0 0 0 0 | VRRES=010b operation unavailable notification | ErrID=2"
    )
    assert c3["flags"] == [] and c3["telemetry_errors"] == []
    assert c3["timeline"]["declared_events"] == 5 and len(c3["timeline"]["events"]) == 5
    assert c3["timeline"]["events"][1] == {
        "time": "12:00:02.500",
        "offset_s": 0.4,
        "kind": "PLAN",
        "name": "ResolverPlan",
        "details": [
            "Resolves the utterance to a VDC command.",
            "intent=Settings  subintent=settings.vdc.body",
            'heard="Open the passenger window"',
        ],
    }
    assert c3["export"]["total"] == 2
    assert c3["export"]["events"][1]["text"] == "That function is not available"
    assert c3["dlt"]["file"].endswith("dlt/case_003.json")
    assert c3["dlt"]["by_level"] == {"Informational": 2}
    assert c3["raw_log"] == (out_dir / c3["log_file"]).read_text()

    assert c4["assertion"]["verdict"] == "MISMATCH"
    assert c4["assertion"]["similarity_pct"] == 82.4
    assert c4["assertion"]["latency_ms"] == 2060
    assert c4["stimulus"]["read_back"] == (
        "FUNC=80 0 0 0 0 00 0 | VRRES=010b operation unavailable notification | ErrID=2"
    )
    assert c4["flags"] == [
        {"field": "read_back", "note": "MISMATCH, bench did not keep the values"},
        {"field": "verdict", "note": "conflicting terms: ['closed'] vs ['open']"},
    ]
    assert c4["telemetry_errors"] == ['Step execution failed: Interpret("Unavailable")']
    assert c4["dlt"]["by_level"] == {"Informational": 1, "Error": 1}
    assert c4["dlt"]["messages"][1]["text"] == "Interpret unavailable in synthetic example"


def test_computed_metrics(out_dir: Path) -> None:
    report = build_report(out_dir, None, None)
    m = report["runs"][0]["computed"]["metrics"]
    assert m["cases_total"] == 2
    assert (m["cases_selected"], m["cases_completed"]) == (2, 2)
    assert (m["passed"], m["failed"], m["other"], m["pass_rate_pct"]) == (1, 1, 0, 50.0)
    assert report["runs"][0]["computed"]["case_outcomes"] == {CASE_3: "pass", CASE_4: "fail"}
    assert m["verdict_counts"] == {"CLOSE": 1, "MISMATCH": 1}
    assert m["latency_ms"] == {"avg": 1940.0, "min": 1820, "max": 2060, "n": 2}
    assert m["similarity_pct"] == {"avg": 86.8, "min": 82.4, "max": 91.3, "n": 2}
    assert m["cases_with_telemetry_errors"] == 1 and m["cases_with_flags"] == 1
    assert m["dlt_messages_by_level"] == {"Informational": 3, "Error": 1}
    assert m["duration_s"] == 18.0
    assert report["runs"][0]["computed"]["consistency"] == []
    assert report["runs"][0]["ai"] == {"status": "skipped", "reason": "built with --no-ai"}


# ---------------------------------------------------------------------- AI cannot edit


def test_model_output_cannot_change_results(out_dir: Path) -> None:
    without_ai = build_report(out_dir, None, None)
    analyst = FakeAnalyst()
    with_ai = build_report(out_dir, None, lambda: analyst)

    run, plain = with_ai["runs"][0], without_ai["runs"][0]
    assert run["facts"] == plain["facts"]
    assert run["facts_sha256"] == plain["facts_sha256"]
    assert run["computed"] == plain["computed"]
    assert with_ai["trend"] == without_ai["trend"]

    ai = run["ai"]
    assert ai["status"] == "ok" and ai["input_sha256"]
    assert set(ai["cases"]) == {CASE_3, CASE_4}  # the unknown case id is gone
    analysis = ai["cases"][CASE_4]
    assert set(analysis) == {
        "likely_cause", "explanation", "evidence", "evidence_dropped", "suggested_action", "confidence",
    }
    assert analysis["evidence"] == ["actual       : The rear window is open"]
    assert analysis["evidence_dropped"] == 1
    assert set(ai["summary"]) == {"headline", "overview", "key_findings", "recommended_actions"}
    assert ai["failure_groups"] == [
        {
            "title": "Resolver error",
            "likely_cause": "system_under_test_error",
            "description": "Same failing step.",
            "case_ids": [CASE_4],  # only the failed case; unknown ids and repeats are gone
            "shared_evidence": ['Step execution failed: Interpret("Unavailable")'],
            "evidence_dropped": 1,
            "suggested_action": "Check the resolver.",
        }
    ]
    assert with_ai["ai_analytics"]["causes_by_run"] == [
        {"stamp": STAMP, "analysed": True, "failed_cases": 1, "failed_by_cause": {"incorrect_response": 1}}
    ]
    assert without_ai["ai_analytics"]["causes_by_run"] == [
        {"stamp": STAMP, "analysed": False, "failed_cases": 1, "failed_by_cause": {}}
    ]
    assert verify_report(out_dir, with_ai) == []


def test_failed_model_call_keeps_the_facts(out_dir: Path) -> None:
    def no_credentials():
        raise RuntimeError("no AWS credentials")

    report = build_report(out_dir, None, no_credentials)
    run = report["runs"][0]
    assert run["ai"] == {"status": "error", "error": "RuntimeError: no AWS credentials"}
    assert run["computed"]["metrics"]["cases_total"] == 2
    assert verify_report(out_dir, report) == []


# -------------------------------------------------------------------------- updating


def test_new_logs_update_the_report_and_the_trend(out_dir: Path) -> None:
    analyst = FakeAnalyst()
    first = build_report(out_dir, None, lambda: analyst)
    assert first["ai_trend"]["status"] == "skipped"
    assert len(analyst.calls) == 3  # cases, failure groups, summary

    # Nothing new: nothing is re-analysed and the content is identical.
    again = build_report(out_dir, first, lambda: analyst)
    assert len(analyst.calls) == 3
    assert content_equal(first, again)

    add_second_run(out_dir)
    second = build_report(out_dir, first, lambda: analyst)
    assert [r["stamp"] for r in second["runs"]] == [STAMP, STAMP_2]
    assert second["runs"][0]["ai"] is first["runs"][0]["ai"]  # kept, not redone
    # + cases and summary (no failed case to group), trend notes, one verdict change
    assert len(analyst.calls) == 7
    assert second["ai_trend"]["status"] == "ok" and second["ai_trend"]["headline"] == "Improved"

    points = second["trend"]["points"]
    assert [p["verdict_counts"] for p in points] == [
        {"CLOSE": 1, "MISMATCH": 1},
        {"CLOSE": 2},
    ]
    assert [p["avg_latency_ms"] for p in points] == [1940.0, 1660.0]
    assert second["trend"]["changes"] == [
        {
            "case_key": "VDC - Error | row 4 | Close the rear window",
            "from_stamp": STAMP,
            "to_stamp": STAMP_2,
            "from_verdict": "MISMATCH",
            "to_verdict": "CLOSE",
            "from_outcome": "fail",
            "to_outcome": "pass",
        }
    ]
    assert [(p["passed"], p["failed"], p["pass_rate_pct"]) for p in points] == [(1, 1, 50.0), (2, 0, 100.0)]
    assert second["trend"]["summary"] == {
        "runs": 2,
        "status": "ok",
        "note": f"Latest run compared with the run before it ({STAMP}).",
        "latest_stamp": STAMP_2,
        "previous_stamp": STAMP,
        "direction": "improving",
        "pass_rate_change_pts": 50.0,
        "passed_change": 1,
        "failed_change": -1,
        "newly_failing": [],
        "newly_passing": ["VDC - Error | row 4 | Close the rear window"],
    }
    assert second["summary"] == {
        "runs_total": 2,
        "runs_completed": 2,
        "cases_selected": 4,
        "cases_completed": 4,
        "cases_executed": 4,
        "passed": 3,
        "failed": 1,
        "other": 0,
        "pass_rate_pct": 75.0,
        "latest": {
            "stamp": STAMP_2,
            "outcome": "completed",
            "cases_selected": 2,
            "cases_completed": 2,
            "cases_executed": 2,
            "passed": 2,
            "failed": 0,
            "other": 0,
            "pass_rate_pct": 100.0,
        },
    }
    assert verify_report(out_dir, second) == []


def test_single_run_and_empty_folder_have_a_trend_section(out_dir: Path, tmp_path: Path) -> None:
    one = build_report(out_dir, None, None)
    assert one["summary"]["runs_total"] == 1 and one["summary"]["pass_rate_pct"] == 50.0
    assert len(one["trend"]["points"]) == 1
    ts = one["trend"]["summary"]
    assert (ts["status"], ts["direction"], ts["previous_stamp"]) == ("single_run", None, None)

    empty = tmp_path / "empty"
    empty.mkdir()
    none = build_report(empty, None, None)
    assert none["summary"]["runs_total"] == 0 and none["summary"]["pass_rate_pct"] is None
    assert none["summary"]["latest"] is None
    assert none["trend"]["summary"]["status"] == "no_runs" and none["trend"]["points"] == []
    assert verify_report(empty, none) == []


def test_pass_fail_rules_are_configurable_and_never_touch_the_verdict(out_dir: Path) -> None:
    strict = {"pass": ["PASS"], "fail": ["MISMATCH", "CLOSE"]}
    analyst = FakeAnalyst()
    default = build_report(out_dir, None, lambda: analyst)
    report = build_report(out_dir, default, lambda: analyst, rules=strict)
    m = report["runs"][0]["computed"]["metrics"]
    assert (m["passed"], m["failed"], m["other"]) == (0, 2, 0)
    assert report["outcome_rules"] == strict
    assert report["runs"][0]["facts"] == default["runs"][0]["facts"]
    assert len(analyst.calls) == 6  # commentary redone, since the totals it saw changed
    assert verify_report(out_dir, report) == []

    unknown = build_report(out_dir, None, None, rules={"pass": ["PASS"], "fail": ["FAIL"]})
    m = unknown["runs"][0]["computed"]["metrics"]
    assert (m["passed"], m["failed"], m["other"], m["pass_rate_pct"]) == (0, 0, 2, 0.0)


def test_removed_logs_stay_as_history(out_dir: Path) -> None:
    add_second_run(out_dir)
    full = build_report(out_dir, None, None)
    for path in list(out_dir.iterdir()):
        if STAMP in path.name:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    after = build_report(out_dir, full, None)
    assert [(r["stamp"], r["source_present"]) for r in after["runs"]] == [
        (STAMP, False),
        (STAMP_2, True),
    ]
    assert after["runs"][0]["facts"] == full["runs"][0]["facts"]
    assert after["trend"] == full["trend"]


def test_changed_logs_drop_stale_commentary(out_dir: Path) -> None:
    analyst = FakeAnalyst()
    first = build_report(out_dir, None, lambda: analyst)
    log = out_dir / f"run_{STAMP}_full/logs/VDC-Error_0003_Open_passenger_window.log"
    log.write_text(log.read_text().replace("1820 ms", "1900 ms"))
    rebuilt = build_report(out_dir, first, None)  # no model available this time
    assert rebuilt["runs"][0]["facts"]["cases"][0]["assertion"]["latency_ms"] == 1900
    assert rebuilt["runs"][0]["ai"]["status"] == "skipped"


# --------------------------------------------------------------------------- verify


def test_verify_detects_an_edited_report(out_dir: Path, tmp_path: Path) -> None:
    report = build_report(out_dir, None, None)
    assert verify_report(out_dir, report) == []

    edited = copy.deepcopy(report)
    edited["runs"][0]["facts"]["cases"][1]["assertion"]["verdict"] = "PASS"
    problems = verify_report(out_dir, edited)
    assert any("do not match their recorded hash" in p for p in problems)
    assert any("differ from the log files" in p for p in problems)

    path = tmp_path / "report" / "execution_report.json"
    write_report(path, report)
    assert json.loads(path.read_text()) == report


# ------------------------------------------------------------------- AI analytics


def three_runs(out_dir: Path) -> None:
    """Row 4 fails, passes, then fails again; row 3 passes throughout."""
    add_run(out_dir, STAMP_2, fixed=True)
    add_run(out_dir, STAMP_3, fixed=False)


def test_flaky_cases_and_failing_streaks_are_counted_without_the_model(out_dir: Path) -> None:
    three_runs(out_dir)
    report = build_report(out_dir, None, None)
    assert report["trend"]["flaky_cases"] == [
        {"case_key": ROW_4, "runs": 3, "flips": 2, "passed": 1, "failed": 2, "other": 0, "latest_outcome": "fail"}
    ]
    assert report["trend"]["failing_streaks"] == {ROW_4: 1}
    analytics = report["ai_analytics"]
    assert analytics["changes"] == {"status": "skipped", "reason": "built with --no-ai", "items": []}
    assert analytics["flaky"] == {"status": "skipped", "reason": "built with --no-ai", "items": []}
    assert verify_report(out_dir, report) == []

    empty = build_report(out_dir.parent / "nothing", None, None)
    assert empty["trend"]["flaky_cases"] == [] and empty["ai_analytics"]["flaky"]["items"] == []


def test_change_explanations_and_flaky_analysis(out_dir: Path) -> None:
    three_runs(out_dir)
    analyst = FakeAnalyst()
    report = build_report(out_dir, None, lambda: analyst)
    plain = build_report(out_dir, None, None)
    assert report["trend"] == plain["trend"] and report["summary"] == plain["summary"]
    assert [r["facts"] for r in report["runs"]] == [r["facts"] for r in plain["runs"]]

    changes = report["ai_analytics"]["changes"]
    assert changes["status"] == "ok"
    assert [(i["from_verdict"], i["to_verdict"]) for i in changes["items"]] == [
        ("MISMATCH", "CLOSE"),
        ("CLOSE", "MISMATCH"),
    ]
    first = changes["items"][0]
    assert first["id"] == f"{ROW_4} @ {STAMP}>{STAMP_2}"
    assert first["explanation"] == "MISMATCH became CLOSE."
    assert first["evidence_before"] == ["actual       : The rear window is open"]
    assert first["evidence_after"] == ["actual       : The rear window is closed."]
    assert first["evidence_dropped"] == 1

    flaky = report["ai_analytics"]["flaky"]
    assert flaky["status"] == "ok" and len(flaky["items"]) == 1
    item = flaky["items"][0]
    assert (item["case_key"], item["pattern"]) == (ROW_4, "system_instability")
    assert item["evidence"] == ['Step execution failed: Interpret("Unavailable")']
    assert item["evidence_dropped"] == 1

    assert [c["failed_by_cause"] for c in report["ai_analytics"]["causes_by_run"]] == [
        {"incorrect_response": 1},
        {},
        {"incorrect_response": 1},
    ]

    # A rebuild asks the model nothing, with or without it, and keeps every item.
    calls = len(analyst.calls)
    again = build_report(out_dir, report, lambda: analyst)
    assert len(analyst.calls) == calls and content_equal(report, again)
    offline = build_report(out_dir, report, None)
    assert offline["ai_analytics"] == report["ai_analytics"]


def test_a_failed_model_call_keeps_earlier_explanations(out_dir: Path) -> None:
    add_run(out_dir, STAMP_2, fixed=True)
    analyst = FakeAnalyst()
    two = build_report(out_dir, None, lambda: analyst)
    assert len(two["ai_analytics"]["changes"]["items"]) == 1

    add_run(out_dir, STAMP_3, fixed=False)

    class Broken(FakeAnalyst):
        def ask(self, task, payload, schema):
            if schema in (CHANGE_SCHEMA, FLAKY_SCHEMA):
                raise AnalystError("rate limit")
            return super().ask(task, payload, schema)

    three = build_report(out_dir, two, lambda: Broken())
    changes = three["ai_analytics"]["changes"]
    assert changes["status"] == "error" and changes["error"] == "rate limit"
    assert changes["items"] == two["ai_analytics"]["changes"]["items"]
    assert three["ai_analytics"]["flaky"]["status"] == "error"
    assert three["summary"]["runs_total"] == 3


# ------------------------------------------------------------------------ questions


def test_question_answering_uses_a_digest_and_filters_references(out_dir: Path) -> None:
    three_runs(out_dir)
    analyst = FakeAnalyst()
    report = build_report(out_dir, None, lambda: analyst)
    before = copy.deepcopy(report)

    digest = report_digest(report)
    assert digest["coverage"] == "Case details are included for every run."
    assert digest["totals_across_all_runs"] == report["summary"]
    assert "raw_log" not in json.dumps(digest)
    small = report_digest(report, max_chars=10)
    assert small["coverage"].startswith("Case details are included for the latest 1 of 3 runs")
    assert "cases" not in small["runs"][0] and "cases" in small["runs"][-1]

    history = [{"question": "How many runs?", "answer": "Three."}, {"question": "", "answer": "skip"}]
    result = answer_question(analyst, report, "  Which case is flaky?  ", history)
    assert result["answer"] == "Answer to: Which case is flaky?"
    assert result["referenced_cases"] == [
        {"case_id": CASE_4, "stamp": STAMP, "excel_row": 4, "utterance": "Close the rear window"}
    ]
    assert set(result) == {"answer", "referenced_cases", "model", "coverage"}
    assert [m["role"] for m in analyst.last_messages] == ["user", "assistant", "user"]
    assert analyst.last_system[1]["cache_control"] == {"type": "ephemeral"}
    assert report == before  # answering never touches the report

    with pytest.raises(ValueError):
        answer_question(analyst, report, "   ")


def test_ask_service_over_http(out_dir: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report" / "execution_report.json"
    analyst = FakeAnalyst()
    server = serve(report_path, lambda: analyst, 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(path: str, body: object | None = None) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    try:
        assert call("/api/health") == (200, {"ok": True, "report": False})
        assert call("/api/ask", {"question": "Anything?"})[0] == 409  # no report yet

        write_report(report_path, build_report(out_dir, None, None))
        assert call("/api/health") == (200, {"ok": True, "report": True})
        status, body = call("/api/ask", {"question": "How many failed?"})
        assert status == 200 and body["answer"] == "Answer to: How many failed?"
        assert body["referenced_cases"][0]["case_id"] == CASE_4
        assert call("/api/ask", {"nope": 1})[0] == 400
        assert call("/api/ask", {"question": " "})[0] == 400
        assert call("/api/other", {"question": "x"})[0] == 404
    finally:
        server.shutdown()
        server.server_close()
