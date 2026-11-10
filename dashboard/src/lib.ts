import { useEffect, useRef, useState } from "react";
import type { Report } from "./types";

// ------------------------------------------------------------------- loading the report

const REPORT_URL = "/execution_report.json";
const POLL_MS = 5000;

export type LoadState =
  | { kind: "loading" }
  | { kind: "missing"; detail: string }
  | { kind: "ready"; report: Report; stale: string | null };

/** Fetches the report and re-checks it every few seconds, so new runs appear on their own. */
export function useReport(): LoadState {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const last = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`${REPORT_URL}?t=${Date.now()}`, { cache: "no-store" });
        const type = res.headers.get("content-type") ?? "";
        if (!res.ok || !type.includes("json")) throw new Error("report file not found");
        const text = await res.text();
        if (cancelled || text === last.current) {
          if (!cancelled) setState((s) => (s.kind === "ready" && s.stale ? { ...s, stale: null } : s));
          return;
        }
        const report = JSON.parse(text) as Report;
        last.current = text;
        setState({ kind: "ready", report, stale: null });
      } catch (err) {
        if (cancelled) return;
        const detail = err instanceof Error ? err.message : String(err);
        // Keep showing the last good report if a later refresh fails.
        setState((s) => (s.kind === "ready" ? { ...s, stale: detail } : { kind: "missing", detail }));
      }
    }
    void load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return state;
}

// ------------------------------------------------------------------------- formatting

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "20261110_120000" → "10 Nov 2026, 12:00:00". The stamp is shown as written, no time zone shift. */
export function stampLong(stamp: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(stamp);
  if (!m) return stamp;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}, ${m[4]}:${m[5]}:${m[6]}`;
}

/** "20261110_120000" → "10 Nov 12:00". */
export function stampShort(stamp: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(stamp);
  if (!m) return stamp;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[4]}:${m[5]}`;
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function localTime(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function duration(seconds: number | null): string {
  if (seconds === null) return "–";
  if (seconds < 60) return `${num(seconds)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds - m * 60)} s`;
}

// --------------------------------------------------------------------------- verdicts

export type Tone = "good" | "warning" | "critical" | "neutral";

// Display only: which colour and icon a verdict label gets. The label itself is always shown
// as the harness wrote it, and no pass rate is derived from this grouping.
const TONES: Record<string, Tone> = {
  PASS: "good",
  PASSED: "good",
  MATCH: "good",
  EXACT: "good",
  OK: "good",
  CLOSE: "warning",
  PARTIAL: "warning",
  FUZZY: "warning",
  MISMATCH: "critical",
  FAIL: "critical",
  FAILED: "critical",
  ERROR: "critical",
  TIMEOUT: "critical",
};
const TONE_ORDER: Tone[] = ["good", "warning", "critical", "neutral"];
export const TONE_ICON: Record<Tone, string> = { good: "✓", warning: "≈", critical: "✕", neutral: "?" };

export function toneOf(verdict: string | null): Tone {
  return TONES[(verdict ?? "").toUpperCase()] ?? "neutral";
}

/** Verdict labels in a stable display order: by tone, then alphabetically. */
export function orderVerdicts(labels: Iterable<string>): string[] {
  return [...new Set(labels)].sort(
    (a, b) => TONE_ORDER.indexOf(toneOf(a)) - TONE_ORDER.indexOf(toneOf(b)) || a.localeCompare(b),
  );
}

export const CAUSE_LABEL: Record<string, string> = {
  none: "No issue",
  wording_variation: "Wording variation",
  incorrect_response: "Incorrect response",
  bench_or_stimulus_setup: "Bench or stimulus setup",
  system_under_test_error: "System-under-test error",
  telemetry_gap: "Telemetry gap",
  inconclusive: "Inconclusive",
};

// ---------------------------------------------------------------------------- layout

/** Width of an element, tracked as it resizes. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** Round axis ticks from 0 up to at least `max`. */
export function ticks(max: number, wanted = 4, integer = false): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / wanted;
  const pow = 10 ** Math.floor(Math.log10(raw));
  let step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  if (integer) step = Math.max(1, Math.round(step));
  const out: number[] = [];
  for (let v = 0; v < max + step - 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}
