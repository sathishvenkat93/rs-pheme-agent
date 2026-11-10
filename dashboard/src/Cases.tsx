import { Fragment, useState } from "react";
import { OutcomeBadge, VerdictBadge } from "./Charts";
import { CAUSE_LABEL, num, stampShort } from "./lib";
import type { CaseAnalysis, CaseFacts, CaseHistoryEntry, Run } from "./types";

export function AiTag({ children }: { children: React.ReactNode }) {
  return <span className="ai-tag">{children}</span>;
}

function Field({ label, flag, children }: { label: string; flag?: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {children}
        {flag && (
          <span className="flag">
            <span aria-hidden="true">⚑</span> {flag}
          </span>
        )}
      </dd>
    </>
  );
}

function CaseDetail({
  c,
  analysis,
  aiNote,
  history,
}: {
  c: CaseFacts;
  analysis: CaseAnalysis | undefined;
  aiNote: string;
  history: CaseHistoryEntry[];
}) {
  const flag = (field: string) => c.flags.find((f) => f.field === field)?.note;
  const extraAssertion = Object.entries(c.assertion).filter(
    ([k]) => !["expected", "actual", "verdict", "similarity_pct", "latency_ms"].includes(k),
  );
  return (
    <div className="detail">
      <section className="detail-facts">
        <h4>Recorded result</h4>
        <dl className="kv">
          <Field label="Expected">{c.assertion.expected ?? "–"}</Field>
          <Field label="Actual" flag={flag("actual")}>
            {c.assertion.actual ?? "–"}
          </Field>
          <Field label="Verdict" flag={flag("verdict")}>
            <VerdictBadge verdict={c.assertion.verdict} />
          </Field>
          <Field label="Similarity">
            {c.assertion.similarity_pct === null ? "–" : `${c.assertion.similarity_pct}%`}
          </Field>
          <Field label="Latency" flag={flag("latency")}>
            {c.assertion.latency_ms === null ? "–" : `${num(c.assertion.latency_ms)} ms`}
          </Field>
          {extraAssertion.map(([k, v]) => (
            <Field key={k} label={k} flag={flag(k)}>
              {String(v)}
            </Field>
          ))}
        </dl>

        {Object.keys(c.stimulus).length > 0 && (
          <>
            <h4>Stimulus sent to VUI</h4>
            <dl className="kv">
              {Object.entries(c.stimulus).map(([k, v]) => (
                <Field key={k} label={k.replace(/_/g, " ")} flag={flag(k)}>
                  <code>{v}</code>
                </Field>
              ))}
            </dl>
          </>
        )}

        {c.telemetry_errors.length > 0 && (
          <>
            <h4>Telemetry errors</h4>
            <ul className="plain">
              {c.telemetry_errors.map((e, i) => (
                <li key={i}>
                  <code>{e}</code>
                </li>
              ))}
            </ul>
          </>
        )}

        {c.timeline.events.length > 0 && (
          <>
            <h4>Telemetry timeline</h4>
            <ol className="timeline">
              {c.timeline.events.map((e, i) => (
                <li key={i} className={e.kind === "ERROR" ? "is-error" : undefined}>
                  <span className="t-time">+{e.offset_s.toFixed(3)}s</span>
                  <span className="t-kind">{e.kind}</span>
                  <span className="t-body">
                    {e.name}
                    {e.details.map((d, j) => (
                      <span className="t-detail" key={j}>
                        {d}
                      </span>
                    ))}
                  </span>
                </li>
              ))}
            </ol>
          </>
        )}

        {c.dlt && (
          <>
            <h4>
              DLT capture <span className="count">{c.dlt.total} messages</span>
            </h4>
            <ul className="plain">
              {c.dlt.messages.map((m, i) => (
                <li key={i} className={m.level === "Error" ? "is-error" : undefined}>
                  <span className="t-kind">{m.level ?? "–"}</span> <code>{m.text ?? m.payload}</code>
                </li>
              ))}
            </ul>
            {c.dlt.truncated && <p className="muted">Showing the first {c.dlt.messages.length}.</p>}
          </>
        )}

        {history.length > 1 && (
          <>
            <h4>This case across runs</h4>
            <ul className="history">
              {history.map((h) => (
                <li key={h.stamp}>
                  <span className="muted">{stampShort(h.stamp)}</span>
                  <VerdictBadge verdict={h.verdict} />
                  <span className="muted">
                    {h.similarity_pct === null ? "" : `${h.similarity_pct}%`}
                    {h.latency_ms === null ? "" : ` · ${num(h.latency_ms)} ms`}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}

        <details>
          <summary>Original log · {c.log_file}</summary>
          <pre>{c.raw_log}</pre>
        </details>
      </section>

      <section className="detail-ai ai-panel">
        <h4>
          <AiTag>AI analysis</AiTag>
        </h4>
        {analysis ? (
          <>
            <p className="ai-cause">
              {CAUSE_LABEL[analysis.likely_cause] ?? analysis.likely_cause}
              <span className="muted"> · {analysis.confidence} confidence</span>
            </p>
            <p>{analysis.explanation}</p>
            {analysis.evidence.length > 0 && (
              <>
                <h5>Quoted from the logs</h5>
                <ul className="plain">
                  {analysis.evidence.map((q, i) => (
                    <li key={i}>
                      <code>{q}</code>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {analysis.evidence_dropped > 0 && (
              <p className="muted">
                {analysis.evidence_dropped} quote{analysis.evidence_dropped > 1 ? "s" : ""} left out: not found
                in the logs.
              </p>
            )}
            {analysis.suggested_action && (
              <>
                <h5>Suggested next step</h5>
                <p>{analysis.suggested_action}</p>
              </>
            )}
          </>
        ) : (
          <p className="muted">{aiNote}</p>
        )}
      </section>
    </div>
  );
}

export function aiUnavailableNote(ai: Run["ai"]): string {
  if (ai.status === "error") return `The AI analysis failed: ${ai.error ?? "unknown error"}`;
  if (ai.status === "skipped") return `No AI analysis: ${ai.reason ?? "skipped"}.`;
  return "No AI analysis for this case.";
}

export function CaseTable({
  run,
  cases,
  history,
}: {
  run: Run;
  cases: CaseFacts[];
  history: Record<string, CaseHistoryEntry[]>;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const hasAi = run.ai.status === "ok";

  if (cases.length === 0) return <p className="muted">No cases match the filters.</p>;
  return (
    <div className="table-wrap">
      <table className="cases">
        <thead>
          <tr>
            <th />
            <th className="numeric">Row</th>
            <th>Utterance</th>
            <th>Expected / actual</th>
            <th>Verdict</th>
            <th>Counted as</th>
            <th className="numeric">Similarity</th>
            <th className="numeric">Latency</th>
            <th>Recorded signals</th>
            {hasAi && (
              <th>
                <AiTag>AI</AiTag> Likely cause
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const isOpen = open.has(c.case_id);
            const analysis = run.ai.cases?.[c.case_id];
            const dltErrors = c.dlt?.by_level.Error ?? 0;
            const signals = [
              c.flags.length > 0 && `${c.flags.length} harness flag${c.flags.length > 1 ? "s" : ""}`,
              c.telemetry_errors.length > 0 &&
                `${c.telemetry_errors.length} telemetry error${c.telemetry_errors.length > 1 ? "s" : ""}`,
              dltErrors > 0 && `${dltErrors} DLT error${dltErrors > 1 ? "s" : ""}`,
            ].filter(Boolean);
            return (
              <Fragment key={c.case_id}>
                <tr className={isOpen ? "is-open" : undefined} onClick={() => toggle(c.case_id)}>
                  <td>
                    <button
                      className="expander"
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Hide" : "Show"} details for row ${c.excel_row}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle(c.case_id);
                      }}
                    >
                      {isOpen ? "▾" : "▸"}
                    </button>
                  </td>
                  <td className="numeric">{c.excel_row ?? "–"}</td>
                  <td>
                    {c.utterance ?? "–"}
                    <div className="muted">{c.category}</div>
                  </td>
                  <td>
                    <div>{c.assertion.expected ?? "–"}</div>
                    <div className="muted">{c.assertion.actual ?? "–"}</div>
                  </td>
                  <td>
                    <VerdictBadge verdict={c.assertion.verdict} />
                  </td>
                  <td>
                    <OutcomeBadge outcome={run.computed.case_outcomes[c.case_id]} />
                  </td>
                  <td className="numeric">
                    {c.assertion.similarity_pct === null ? "–" : `${c.assertion.similarity_pct}%`}
                  </td>
                  <td className="numeric">
                    {c.assertion.latency_ms === null ? "–" : `${num(c.assertion.latency_ms)} ms`}
                  </td>
                  <td>{signals.length ? signals.join(", ") : <span className="muted">None</span>}</td>
                  {hasAi && (
                    <td>{analysis ? (CAUSE_LABEL[analysis.likely_cause] ?? analysis.likely_cause) : "–"}</td>
                  )}
                </tr>
                {isOpen && (
                  <tr className="detail-row">
                    <td colSpan={hasAi ? 10 : 9}>
                      <CaseDetail
                        c={c}
                        analysis={analysis}
                        aiNote={aiUnavailableNote(run.ai)}
                        history={history[c.key] ?? []}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
