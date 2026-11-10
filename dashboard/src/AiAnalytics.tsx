import { useEffect, useRef, useState } from "react";
import { AiTag, aiUnavailableNote } from "./Cases";
import { OutcomeBadge, StackedColumns, VerdictBadge, type StackSeries } from "./Charts";
import { CAUSE_LABEL, localTime, stampLong, stampShort } from "./lib";
import type { AiSection, AskAnswer, CaseFacts, Report, Run } from "./types";

// Fixed order and colour per cause, so a colour means the same cause in every chart.
const CAUSE_ORDER = [
  "incorrect_response",
  "system_under_test_error",
  "bench_or_stimulus_setup",
  "wording_variation",
  "telemetry_gap",
  "none",
  "inconclusive",
];
const CAUSE_SERIES: StackSeries[] = CAUSE_ORDER.map((key) => ({
  key,
  label: CAUSE_LABEL[key] ?? key,
  className: `cause-${key}`,
}));

const PATTERN_LABEL: Record<string, string> = {
  timing: "Timing",
  bench_or_stimulus_state: "Bench or stimulus state",
  system_instability: "System instability",
  expected_text_borderline: "Response wording near the match threshold",
  inconclusive: "Inconclusive",
};

function CauseKey({ cause }: { cause: string }) {
  return (
    <span className="cause-key">
      <span className={`swatch cause-${cause}`} aria-hidden="true" />
      {CAUSE_LABEL[cause] ?? cause}
    </span>
  );
}

function Quotes({ title, quotes }: { title: string; quotes: string[] }) {
  if (quotes.length === 0) return null;
  return (
    <>
      <h5>{title}</h5>
      <ul className="plain">
        {quotes.map((q, i) => (
          <li key={i}>
            <code>{q}</code>
          </li>
        ))}
      </ul>
    </>
  );
}

function sectionNote(section: AiSection<unknown>, what: string): string | null {
  if (section.status === "error") return `The AI analysis of ${what} failed: ${section.error ?? "unknown error"}`;
  if (section.status === "skipped" && section.reason === "built with --no-ai")
    return `No AI analysis of ${what}: built with --no-ai.`;
  return null;
}

// ------------------------------------------------------------------ this run


function RunSummary({ run }: { run: Run }) {
  const ai = run.ai;
  if (ai.status !== "ok" || !ai.summary) return null;
  return (
    <div className="card ai-panel">
      <h3>
        Summary of this run
        <span className="muted ai-meta">
          {ai.model} · {localTime(ai.generated_at)}
        </span>
      </h3>
      <p className="ai-headline">{ai.summary.headline}</p>
      <p>{ai.summary.overview}</p>
      <div className="two-col">
        {ai.summary.key_findings.length > 0 && (
          <div>
            <h5>Key findings</h5>
            <ul>
              {ai.summary.key_findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        {ai.summary.recommended_actions.length > 0 && (
          <div>
            <h5>Recommended actions</h5>
            <ul>
              {ai.summary.recommended_actions.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {ai.input_truncated && <p className="muted">Some long captures were shortened before the model read them.</p>}
    </div>
  );
}

/** Failed cases of the run by the model's cause label: ranked bars, value at the tip. */
function CauseBars({ counts, failed }: { counts: Record<string, number>; failed: number }) {
  const rows = CAUSE_ORDER.filter((c) => counts[c]).sort((a, b) => counts[b] - counts[a]);
  if (failed === 0) return <p className="muted">No failed cases in this run.</p>;
  if (rows.length === 0) return <p className="muted">The failed cases of this run have no cause label yet.</p>;
  const max = Math.max(...rows.map((c) => counts[c]));
  return (
    <table className="bars">
      <tbody>
        {rows.map((c) => (
          <tr key={c}>
            <th scope="row">{CAUSE_LABEL[c] ?? c}</th>
            <td>
              <span className={`hbar cause-${c}`} style={{ width: `${(counts[c] / max) * 100}%` }} />
              <span className="hbar-value">{counts[c]}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FailureGroups({
  run,
  report,
  onPickCase,
}: {
  run: Run;
  report: Report;
  onPickCase: (caseId: string) => void;
}) {
  const groups = run.ai.failure_groups ?? [];
  const failed = run.facts.cases.filter((c) => run.computed.case_outcomes[c.case_id] === "fail");
  const byId = new Map<string, CaseFacts>(run.facts.cases.map((c) => [c.case_id, c]));
  const grouped = new Set(groups.flatMap((g) => g.case_ids));
  const ungrouped = failed.filter((c) => !grouped.has(c.case_id));
  const isLatest = report.runs[report.runs.length - 1].stamp === run.stamp;

  const caseButton = (c: CaseFacts) => {
    const streak = isLatest ? report.trend.failing_streaks[c.key] : undefined;
    return (
      <li key={c.case_id}>
        <button className="link" onClick={() => onPickCase(c.case_id)}>
          Row {c.excel_row ?? "–"} · {c.utterance ?? c.case_id}
        </button>
        {streak !== undefined && streak > 1 && <span className="muted"> · failed in the last {streak} runs</span>}
      </li>
    );
  };

  if (failed.length === 0) return <p className="muted">No failed cases in this run, so there is nothing to group.</p>;
  return (
    <>
      <ul className="groups">
        {groups.map((g, i) => (
          <li key={i}>
            <p className="group-title">
              {g.title}
              <span className="count">
                {g.case_ids.length} case{g.case_ids.length > 1 ? "s" : ""}
              </span>
            </p>
            <p>
              <CauseKey cause={g.likely_cause} />
            </p>
            {g.description && <p>{g.description}</p>}
            <Quotes title="Quoted from the logs" quotes={g.shared_evidence} />
            {g.suggested_action && (
              <>
                <h5>Suggested next step</h5>
                <p>{g.suggested_action}</p>
              </>
            )}
            <h5>Cases</h5>
            <ul className="plain">{g.case_ids.map((id) => byId.get(id)).filter((c) => c !== undefined).map(caseButton)}</ul>
          </li>
        ))}
      </ul>
      {ungrouped.length > 0 && (
        <>
          <h5>
            Not in a group <span className="count">{ungrouped.length}</span>
          </h5>
          <ul className="plain">{ungrouped.map(caseButton)}</ul>
        </>
      )}
      {run.ai.failure_groups_truncated && (
        <p className="muted">This run has more failed cases than the model was shown; the rest are listed as not in a group.</p>
      )}
    </>
  );
}

function ChangesInRun({ run, report }: { run: Run; report: Report }) {
  const changes = report.trend.changes.filter((c) => c.to_stamp === run.stamp);
  const section = report.ai_analytics.changes;
  const explained = new Map(section.items.map((i) => [i.id, i]));
  const note = sectionNote(section, "verdict changes");
  if (changes.length === 0) {
    return (
      <p className="muted">
        {report.runs[0].stamp === run.stamp
          ? "This is the first run in the report, so there is no earlier result to compare with."
          : "No case changed verdict in this run compared with its previous result."}
      </p>
    );
  }
  return (
    <ul className="changes">
      {changes.map((c) => {
        const ai = explained.get(`${c.case_key} @ ${c.from_stamp}>${c.to_stamp}`);
        return (
          <li key={c.case_key}>
            <div>{c.case_key}</div>
            <div className="change-line">
              <VerdictBadge verdict={c.from_verdict} />
              <span aria-label="changed to">→</span>
              <VerdictBadge verdict={c.to_verdict} />
              <span className="muted">since {stampShort(c.from_stamp)}</span>
            </div>
            {ai ? (
              <div className="explained">
                <p>
                  {ai.explanation} <span className="muted">({ai.confidence} confidence)</span>
                </p>
                {ai.differences.length > 0 && (
                  <ul>
                    {ai.differences.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                )}
                {(ai.evidence_before.length > 0 || ai.evidence_after.length > 0) && (
                  <details>
                    <summary>Quoted from the two logs</summary>
                    <Quotes title={`Before · ${stampShort(c.from_stamp)}`} quotes={ai.evidence_before} />
                    <Quotes title={`After · ${stampShort(c.to_stamp)}`} quotes={ai.evidence_after} />
                  </details>
                )}
              </div>
            ) : (
              <p className="muted explained">{note ?? "No explanation for this change yet."}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// --------------------------------------------------------------- across runs

function FlakyCases({ report }: { report: Report }) {
  const flaky = report.trend.flaky_cases;
  const section = report.ai_analytics.flaky;
  const analysed = new Map(section.items.map((i) => [i.case_key, i]));
  const note = sectionNote(section, "flaky cases");
  if (flaky.length === 0) {
    return (
      <p className="muted">
        No flaky cases: no case has switched between passed and failed two or more times across the runs in the
        report.
      </p>
    );
  }
  return (
    <ul className="changes">
      {flaky.map((f) => {
        const ai = analysed.get(f.case_key);
        const history = report.trend.case_history[f.case_key] ?? [];
        return (
          <li key={f.case_key}>
            <div>{f.case_key}</div>
            <p className="muted">
              Changed outcome {f.flips} times in {f.runs} runs: {f.passed} passed, {f.failed} failed
              {f.other > 0 ? `, ${f.other} other` : ""}.
            </p>
            <ol className="sequence" aria-label="Outcome in each run, oldest first">
              {history.map((h) => (
                <li key={h.stamp}>
                  <span className="muted">{stampShort(h.stamp)}</span>
                  <OutcomeBadge outcome={h.outcome} />
                </li>
              ))}
            </ol>
            {ai ? (
              <div className="explained">
                <p className="ai-cause">
                  {PATTERN_LABEL[ai.pattern] ?? ai.pattern}
                  <span className="muted"> · {ai.confidence} confidence</span>
                </p>
                <p>{ai.explanation}</p>
                <Quotes title="Quoted from the logs" quotes={ai.evidence} />
                {ai.suggested_action && (
                  <>
                    <h5>Suggested next step</h5>
                    <p>{ai.suggested_action}</p>
                  </>
                )}
              </div>
            ) : (
              <p className="muted explained">{note ?? "No analysis of this case yet."}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function TrendNotes({ report }: { report: Report }) {
  const ai = report.ai_trend;
  if (ai.status !== "ok") {
    return (
      <p className="muted">
        {ai.status === "error" ? `The AI analysis failed: ${ai.error}` : `No trend notes: ${ai.reason}.`}
      </p>
    );
  }
  return (
    <>
      <p className="ai-headline">{ai.headline}</p>
      <p>{ai.narrative}</p>
      {ai.notable_changes && ai.notable_changes.length > 0 && (
        <ul>
          {ai.notable_changes.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </>
  );
}

// ------------------------------------------------------------------------ ask

interface Turn {
  question: string;
  answer?: AskAnswer;
  error?: string;
}

const SUGGESTIONS = [
  "Which cases failed in the latest run, and why?",
  "What changed since the previous run?",
  "Which cases have failed in every run?",
];

async function getJson(url: string, init?: RequestInit): Promise<{ ok: boolean; body: Record<string, unknown> | null }> {
  const res = await fetch(url, init);
  const isJson = (res.headers.get("content-type") ?? "").includes("json");
  return { ok: res.ok && isJson, body: isJson ? ((await res.json()) as Record<string, unknown>) : null };
}

function Ask({ onPickCase }: { onPickCase: (caseId: string) => void }) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);

  // The question service is a separate local process; keep checking until it is there.
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const { ok } = await getJson("/api/health");
        if (!cancelled) setAvailable(ok);
      } catch {
        if (!cancelled) setAvailable(false);
      }
    };
    void check();
    const timer = setInterval(check, 10_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    const history = turns.filter((t) => t.answer).map((t) => ({ question: t.question, answer: t.answer!.answer }));
    setTurns((prev) => [...prev, { question: text }]);
    setDraft("");
    setBusy(true);
    let result: Pick<Turn, "answer" | "error">;
    try {
      const { ok, body } = await getJson("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, history }),
      });
      result = ok && body
        ? { answer: body as unknown as AskAnswer }
        : { error: typeof body?.error === "string" ? body.error : "The question service did not answer." };
    } catch {
      result = { error: "The question service could not be reached." };
    }
    setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, ...result } : t)));
    setBusy(false);
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  return (
    <div className="card ai-panel">
      <h3>Ask about the report</h3>
      {available === false && (
        <p className="notice">
          The question service is not running. Start it from the project folder with{" "}
          <code>uv run pheme-report serve</code>; this box connects on its own.
        </p>
      )}
      {turns.length > 0 && (
        <ol className="turns">
          {turns.map((t, i) => (
            <li key={i}>
              <p className="turn-q">{t.question}</p>
              {t.answer && (
                <>
                  <p className="turn-a">{t.answer.answer}</p>
                  {t.answer.referenced_cases.length > 0 && (
                    <ul className="refs">
                      {t.answer.referenced_cases.map((c) => (
                        <li key={c.case_id}>
                          <button className="chip" onClick={() => onPickCase(c.case_id)}>
                            {stampShort(c.stamp)} · row {c.excel_row ?? "–"} · {c.utterance ?? c.case_id}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              {t.error && <p className="turn-error">{t.error}</p>}
              {!t.answer && !t.error && <p className="muted">Reading the report…</p>}
            </li>
          ))}
        </ol>
      )}
      <div ref={endRef} />
      {turns.length === 0 && (
        <ul className="refs">
          {SUGGESTIONS.map((q) => (
            <li key={q}>
              <button className="chip" disabled={!available || busy} onClick={() => void ask(q)}>
                {q}
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(draft);
        }}
      >
        <input
          type="search"
          aria-label="Question about the report"
          placeholder="Ask about runs, cases, failures or trends"
          value={draft}
          maxLength={2000}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="primary" type="submit" disabled={!available || busy || !draft.trim()}>
          Ask
        </button>
      </form>
      <p className="muted">
        The model answers from the report only. An answer is not saved and does not change the report.
      </p>
    </div>
  );
}

// -------------------------------------------------------------------- section

export function AiAnalytics({
  report,
  run,
  onSelectRun,
  onPickCase,
}: {
  report: Report;
  run: Run;
  onSelectRun: (stamp: string) => void;
  onPickCase: (caseId: string) => void;
}) {
  const causes = report.ai_analytics.causes_by_run;
  const ofRun = causes.find((c) => c.stamp === run.stamp);
  const analysedRuns = causes.filter((c) => c.analysed).length;
  const shownSeries = CAUSE_SERIES.filter((s) => causes.some((c) => c.failed_by_cause[s.key]));
  const aiOk = run.ai.status === "ok";

  return (
    <section aria-labelledby="ai-h">
      <h2 id="ai-h">
        AI analytics <AiTag>AI</AiTag>
      </h2>
      <p className="muted section-intro">
        Written by the Bedrock model, or counted from its labels. It explains the recorded results above and cannot
        change them.
      </p>

      <h3 className="subhead">Run {stampLong(run.stamp)}</h3>
      {!aiOk && <p className="notice">{aiUnavailableNote(run.ai)}</p>}
      <RunSummary run={run} />
      {aiOk && (
        <div className="two-col">
          <div className="card ai-panel">
            <h3>
              Failed cases by likely cause <span className="count">{ofRun?.failed_cases ?? 0}</span>
            </h3>
            <CauseBars counts={ofRun?.failed_by_cause ?? {}} failed={ofRun?.failed_cases ?? 0} />
          </div>
          <div className="card ai-panel">
            <h3>
              Failure groups <span className="count">{run.ai.failure_groups?.length ?? 0}</span>
            </h3>
            <FailureGroups run={run} report={report} onPickCase={onPickCase} />
          </div>
        </div>
      )}
      <div className="card ai-panel">
        <h3>Why verdicts changed in this run</h3>
        <ChangesInRun run={run} report={report} />
      </div>

      <h3 className="subhead">Across runs</h3>
      {report.runs.length > 1 && analysedRuns > 0 && shownSeries.length > 0 && (
        <div className="card ai-panel">
          <h3>Failed cases per run, by likely cause</h3>
          <p className="muted">
            Select a column to show that run.
            {analysedRuns < causes.length ? ` ${causes.length - analysedRuns} run(s) have no AI analysis and show no column.` : ""}
          </p>
          <StackedColumns
            points={causes.map((c) => ({ stamp: c.stamp, counts: c.failed_by_cause }))}
            series={shownSeries}
            selected={run.stamp}
            onSelect={onSelectRun}
            label="Failed cases per run, split by likely cause"
            totalLabel="failed cases with a cause"
            legend={
              <ul className="legend">
                {shownSeries.map((s) => (
                  <li key={s.key}>
                    <CauseKey cause={s.key} />
                  </li>
                ))}
              </ul>
            }
          />
        </div>
      )}
      <div className="two-col">
        <div className="card ai-panel">
          <h3>
            Flaky cases <span className="count">{report.trend.flaky_cases.length}</span>
          </h3>
          <FlakyCases report={report} />
        </div>
        <div className="card ai-panel">
          <h3>Trend notes</h3>
          <TrendNotes report={report} />
        </div>
      </div>

      <h3 className="subhead">Questions</h3>
      <Ask onPickCase={onPickCase} />
    </section>
  );
}
