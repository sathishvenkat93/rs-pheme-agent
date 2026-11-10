"""Deterministic parsers for the files a test execution writes under ``out/``.

Everything in this module is plain text and JSON handling: no model is involved, and every
value is copied from the source file as written. This is the only code that produces the
``facts`` section of the report.

Layout of ``out/`` (``<stamp>`` is e.g. ``20261110_120000``)::

    execution_<stamp>.json                  run metadata
    vui_baseline_<stamp>.json               bench baseline
    run_<stamp>_<name>/logs/<case>.log          per-case result log
    run_<stamp>_<name>/logs/<case>.export.log   per-case telemetry export (JSON)
    run_<stamp>_<name>/dlt/case_<row>.json      per-case DLT capture (JSON)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

# Messages kept per case for the export and DLT captures. Totals are always recorded, so a
# capped list is visible as such (``truncated: true``).
MAX_EVENTS_PER_CASE = 200

_STAMP = r"(\d{8}_\d{6})"
_EXECUTION_RE = re.compile(rf"^execution_{_STAMP}\.json$")
_BASELINE_RE = re.compile(rf"^vui_baseline_{_STAMP}\.json$")
_RUN_DIR_RE = re.compile(rf"^run_{_STAMP}_(.+)$")
_DLT_FILE_RE = re.compile(r"^case_0*(\d+)\.json$")

_SECTION_RE = re.compile(r"^---\s*(.+?)\s*---\s*$")
_KV_RE = re.compile(r"^([A-Za-z][\w\- ]*?)\s*:\s?(.*)$")
_HEADER_ROW_RE = re.compile(r"^excel row\s+(\d+)$", re.IGNORECASE)
_VERDICT_RE = re.compile(r"^(.*?)(?:\s*\(similarity\s+([\d.]+)\s*%\))?\s*$")
_LATENCY_RE = re.compile(r"^([\d.]+)\s*ms\s*$")
_TIMELINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+\+\s*([\d.]+)s\s+(\S+)\s*(.*)$")
_DECLARED_EVENTS_RE = re.compile(r"\((\d+)\s+events?\)")
_DLT_LEVEL_RE = re.compile(r"::(\w+)::")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    """Hash of a JSON value, independent of key order and whitespace."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_bytes(text.encode("utf-8"))


def _number(text: str) -> int | float:
    """The number as written: ``1820`` stays an int, ``91.3`` a float."""
    return float(text) if "." in text else int(text)


def _split_note(value: str) -> tuple[str, str | None]:
    """Split a ``value   <-- note`` line. The harness appends such notes to flag a line."""
    if "<--" not in value:
        return value.strip(), None
    head, note = value.split("<--", 1)
    return head.strip(), note.strip()


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


# ------------------------------------------------------------------------------ case log


def parse_case_log(text: str) -> dict[str, Any]:
    """Parse one ``<case>.log`` file into facts. Unknown sections are kept as raw lines."""
    case: dict[str, Any] = {
        "sheet": None,
        "excel_row": None,
        "category": None,
        "utterance": None,
        "stimulus": {},
        "assertion": {
            "expected": None,
            "actual": None,
            "verdict": None,
            "similarity_pct": None,
            "latency_ms": None,
        },
        "flags": [],
        "telemetry_errors": [],
        "timeline": {"declared_events": None, "events": []},
        "other_sections": {},
    }
    section = "header"
    section_title = ""
    header_seen = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) == {"="}:
            continue

        m = _SECTION_RE.match(stripped)
        if m:
            section_title = m.group(1)
            lowered = section_title.lower()
            if lowered.startswith("stimulus"):
                section = "stimulus"
            elif lowered.startswith("assertion"):
                section = "assertion"
            elif lowered.startswith("telemetry errors"):
                section = "errors"
            elif lowered.startswith("telemetry timeline"):
                section = "timeline"
                declared = _DECLARED_EVENTS_RE.search(section_title)
                if declared:
                    case["timeline"]["declared_events"] = int(declared.group(1))
            else:
                section = "other"
                case["other_sections"][section_title] = []
            continue

        if section == "header":
            if not header_seen and "|" in stripped and not _KV_RE.match(stripped):
                header_seen = True
                parts = [p.strip() for p in stripped.split("|")]
                case["sheet"] = parts[0] or None
                for part in parts[1:]:
                    row = _HEADER_ROW_RE.match(part)
                    if row:
                        case["excel_row"] = int(row.group(1))
                if len(parts) >= 3:
                    case["category"] = parts[-1] or None
                continue
            kv = _KV_RE.match(stripped)
            if kv:
                value, note = _split_note(kv.group(2))
                key = _key(kv.group(1))
                if key == "utterance":
                    case["utterance"] = value
                else:
                    case["other_sections"].setdefault("header", []).append(stripped)
                if note:
                    case["flags"].append({"field": key, "note": note})
            else:
                case["other_sections"].setdefault("header", []).append(stripped)

        elif section in ("stimulus", "assertion"):
            kv = _KV_RE.match(stripped)
            if not kv:
                case["other_sections"].setdefault(section_title, []).append(stripped)
                continue
            key = _key(kv.group(1))
            value, note = _split_note(kv.group(2))
            if note:
                case["flags"].append({"field": key, "note": note})
            if section == "stimulus":
                case["stimulus"][key] = value
            elif key == "verdict":
                vm = _VERDICT_RE.match(value)
                case["assertion"]["verdict"] = (vm.group(1).strip() if vm else value) or None
                if vm and vm.group(2):
                    case["assertion"]["similarity_pct"] = _number(vm.group(2))
            elif key == "latency":
                lm = _LATENCY_RE.match(value)
                if lm:
                    case["assertion"]["latency_ms"] = _number(lm.group(1))
                else:
                    case["assertion"]["latency"] = value
            else:
                case["assertion"][key] = value

        elif section == "errors":
            case["telemetry_errors"].append(stripped)

        elif section == "timeline":
            tm = _TIMELINE_RE.match(stripped)
            if tm:
                case["timeline"]["events"].append(
                    {
                        "time": tm.group(1),
                        "offset_s": _number(tm.group(2)),
                        "kind": tm.group(3),
                        "name": tm.group(4).strip(),
                        "details": [],
                    }
                )
            elif case["timeline"]["events"]:
                case["timeline"]["events"][-1]["details"].append(stripped)
            else:
                case["other_sections"].setdefault(section_title, []).append(stripped)

        else:
            case["other_sections"][section_title].append(stripped)

    case["raw_log"] = text
    return case


# --------------------------------------------------------------------- telemetry export


def _meta_of(data: Any) -> dict[str, Any]:
    """The first ``{"meta": {...}}`` holder inside an event's ``data`` (step, plan, ...)."""
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get("meta"), dict):
                return value
    return {}


def parse_export_log(text: str) -> dict[str, Any]:
    events = json.loads(text)
    if not isinstance(events, list):
        raise ValueError("expected a JSON array of events")
    out = []
    for ev in events[:MAX_EVENTS_PER_CASE]:
        if not isinstance(ev, dict):
            continue
        holder = _meta_of(ev.get("data"))
        meta = holder.get("meta", {})
        out.append(
            {
                "id": ev.get("id"),
                "received_at": ev.get("receivedAt"),
                "session_id": ev.get("sessionId"),
                "type": ev.get("type"),
                "name": meta.get("name"),
                "description": meta.get("description"),
                "text": holder.get("text"),
            }
        )
    return {"total": len(events), "truncated": len(events) > MAX_EVENTS_PER_CASE, "events": out}


# -------------------------------------------------------------------------------- DLT


def parse_dlt(text: str) -> dict[str, Any]:
    messages = json.loads(text)
    if not isinstance(messages, list):
        raise ValueError("expected a JSON array of DLT messages")
    by_level: dict[str, int] = {}
    out = []
    for i, entry in enumerate(messages):
        if not isinstance(entry, dict):
            continue
        msg = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        payload = msg.get("payload")
        level = None
        inner_text = None
        if isinstance(payload, str):
            lm = _DLT_LEVEL_RE.search(payload)
            if lm:
                level = lm.group(1)
                tail = payload[lm.end() :]
                try:
                    inner = json.loads(tail)
                    inner_text = inner.get("fields", {}).get("message")
                except (ValueError, AttributeError):
                    inner_text = None
        by_level[level or "unknown"] = by_level.get(level or "unknown", 0) + 1
        if i < MAX_EVENTS_PER_CASE:
            out.append(
                {
                    "index": entry.get("index"),
                    "app_id": msg.get("app_id"),
                    "ctx_id": msg.get("ctx_id"),
                    "level": level,
                    "text": inner_text,
                    "payload": payload,
                }
            )
    return {
        "total": len(messages),
        "truncated": len(messages) > MAX_EVENTS_PER_CASE,
        "by_level": by_level,
        "messages": out,
    }


# ------------------------------------------------------------------------------- runs


def discover_stamps(out_dir: Path) -> list[str]:
    """Every run stamp that has at least one file or folder under ``out_dir``."""
    stamps: set[str] = set()
    if not out_dir.is_dir():
        return []
    for entry in out_dir.iterdir():
        for pattern in (_EXECUTION_RE, _BASELINE_RE, _RUN_DIR_RE):
            m = pattern.match(entry.name)
            if m:
                stamps.add(m.group(1))
    return sorted(stamps)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_run(out_dir: Path, stamp: str) -> dict[str, Any]:
    """Read every file of one run. Returns ``facts``, ``sources`` and ``parse_warnings``."""
    sources: list[dict[str, Any]] = []
    warnings: list[str] = []

    def track(path: Path) -> str:
        data = path.read_bytes()
        rel = path.relative_to(out_dir).as_posix()
        sources.append({"path": rel, "sha256": sha256_bytes(data), "bytes": len(data)})
        return data.decode("utf-8", errors="replace")

    def load_json_file(name: str) -> Any:
        path = out_dir / name
        if not path.is_file():
            return None
        text = track(path)
        try:
            return json.loads(text)
        except ValueError as exc:
            warnings.append(f"{name}: not valid JSON ({exc})")
            return None

    execution = load_json_file(f"execution_{stamp}.json")
    baseline = load_json_file(f"vui_baseline_{stamp}.json")

    cases: list[dict[str, Any]] = []
    dlt_by_row: dict[int, list[tuple[str, dict[str, Any]]]] = {}

    run_dirs = sorted(
        d for d in out_dir.iterdir() if d.is_dir() and d.name.startswith(f"run_{stamp}_")
    )
    for run_dir in run_dirs:
        logs_dir = run_dir / "logs"
        if logs_dir.is_dir():
            for log_path in sorted(logs_dir.glob("*.log")):
                if log_path.name.endswith(".export.log"):
                    continue
                rel = log_path.relative_to(out_dir).as_posix()
                case = parse_case_log(track(log_path))
                stem = log_path.name[: -len(".log")]
                case = {"case_id": f"{stamp}/{stem}", "log_file": rel, **case}
                case["export"] = None
                export_path = logs_dir / f"{stem}.export.log"
                if export_path.is_file():
                    export_rel = export_path.relative_to(out_dir).as_posix()
                    try:
                        case["export"] = {"file": export_rel, **parse_export_log(track(export_path))}
                    except ValueError as exc:
                        warnings.append(f"{export_rel}: {exc}")
                case["dlt"] = None
                cases.append(case)

        dlt_dir = run_dir / "dlt"
        if dlt_dir.is_dir():
            for dlt_path in sorted(dlt_dir.glob("*.json")):
                rel = dlt_path.relative_to(out_dir).as_posix()
                text = track(dlt_path)
                m = _DLT_FILE_RE.match(dlt_path.name)
                if not m:
                    warnings.append(f"{rel}: file name has no case row, not linked to a case")
                    continue
                try:
                    dlt_by_row.setdefault(int(m.group(1)), []).append((rel, parse_dlt(text)))
                except ValueError as exc:
                    warnings.append(f"{rel}: {exc}")

    # A DLT capture is named by excel row only. Link it when that row identifies one case.
    for row, captures in sorted(dlt_by_row.items()):
        matches = [c for c in cases if c["excel_row"] == row]
        if len(matches) == 1 and len(captures) == 1:
            rel, dlt = captures[0]
            matches[0]["dlt"] = {"file": rel, **dlt}
        else:
            for rel, _ in captures:
                warnings.append(
                    f"{rel}: row {row} matches {len(matches)} case logs and "
                    f"{len(captures)} DLT files, not linked to a case"
                )

    cases.sort(key=lambda c: (c["excel_row"] is None, c["excel_row"] or 0, c["case_id"]))
    for case in cases:
        case["key"] = " | ".join(
            [
                str(case["sheet"]),
                f"row {case['excel_row']}",
                str(case["utterance"]),
            ]
        )

    sources.sort(key=lambda s: s["path"])
    return {
        "stamp": stamp,
        "facts": {"execution": execution, "baseline": baseline, "cases": cases},
        "sources": sources,
        "parse_warnings": warnings,
    }
