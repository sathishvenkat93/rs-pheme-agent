import { useMemo, useState } from "react";
import { AiAnalytics } from "./AiAnalytics";
import { AiTag, CaseTable } from "./Cases";
import { MetricOverRuns, VerdictBadge, VerdictSplit, VerdictsOverRuns } from "./Charts";
import { duration, localTime, num, orderVerdicts, stampLong, stampShort, useReport } from "./lib";
import type { Report, Run, TrendPoint } from "./types";

function Delta({
  now,
  before,
  unit,
  digits = 0,
  upIsGood,
  since,
}: {
  now: number | null | undefined;
  before: number | null | undefined;
  unit: string;
  digits?: number;
  upIsGood?: boolean;
  since: string;
}) {
  if (now === null || now === undefined || before === null || before === undefined) return null;
  const diff = Number((now - before).toFixed(digits));
  if (diff === 0) return <p className="delta">No change vs {since}</p>;
  const tone = upIsGood === undefined ? "" : diff > 0 === upIsGood ? " is-good" : " is-bad";
  return (
    <p className={`delta${tone}`}>
      <span aria-hidden="true">{diff > 0 ? "▲" : "▼"}</span> {diff > 0 ? "+" : "−"}
      {num(Math.abs(diff), digits)}
      {unit} vs {since}
    </p>
  );
}

function Tile({ label, value, note, children }: { label: string; value: string; note?: string; children?: React.ReactNode }) {
  return (
    <div className="tile">
      <p className="tile-label">{label}</p>
      <p className="tile-value">{value}</p>
      {note && <p className="tile-note">{note}</p>}
      {children}
    </div>
  );
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–";
  if (Array.isArray(value)) return value.map(String).join(" ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function RunSection({ run, previous, rules }: { run: Run; previous: Run | undefined; rules: Report["outcome_rules"] }) {
  const m = run.computed.metrics;
  const pm = previous?.computed.metrics;
  const since = previous ? stampShort(previous.stamp) : "";
  const execution = run.facts.execution;
  const selected = typeof execution?.selected === "number" ? execution.selected : null;
  const notes = [...run.computed.consistency, ...run.parse_warnings];

  return (
    <section aria-labelledby="run-h">
      <h2 id="run-h">Run {stampLong(run.stamp)}</h2>
      {!run.source_present && (
        <p className="notice">The log files of this run are no longer in the logs folder. The report keeps what was recorded.</p>
      )}

      <div className="tiles">
        <Tile label="Cases run" value={num(m.cases_total)} note={selected === null ? undefined : `of ${num(selected)} selected`}>
          <Delta now={m.cases_total} before={pm?.cases_total} unit="" since={since} />
        </Tile>
        <Tile label="Passed" value={num(m.passed)}>
          <Delta now={m.passed} before={pm?.passed} unit="" upIsGood since={since} />
        </Tile>
        <Tile label="Failed" value={num(m.failed)} note={m.other > 0 ? `${num(m.other)} other (verdict in neither list)` : undefined}>
          <Delta now={m.failed} before={pm?.failed} unit="" upIsGood={false} since={since} />
        </Tile>
        <Tile label="Pass rate" value={m.pass_rate_pct === null ? "–" : `${num(m.pass_rate_pct, 1)}%`}>
          <Delta now={m.pass_rate_pct} before={pm?.pass_rate_pct} unit=" pts" digits={1} upIsGood since={since} />
        </Tile>
        <Tile
          label="Average similarity"
          value={m.similarity_pct ? `${num(m.similarity_pct.avg, 1)}%` : "–"}
          note={m.similarity_pct ? `${m.similarity_pct.min}% to ${m.similarity_pct.max}%` : undefined}
        >
          <Delta now={m.similarity_pct?.avg} before={pm?.similarity_pct?.avg} unit=" pts" digits={1} upIsGood since={since} />
        </Tile>
        <Tile
          label="Average latency"
          value={m.latency_ms ? `${num(m.latency_ms.avg)} ms` : "–"}
          note={m.latency_ms ? `${num(m.latency_ms.min)} to ${num(m.latency_ms.max)} ms` : undefined}
        >
          <Delta now={m.latency_ms?.avg} before={pm?.latency_ms?.avg} unit=" ms" upIsGood={false} since={since} />
        </Tile>
        <Tile label="Cases with telemetry errors" value={num(m.cases_with_telemetry_errors)}>
          <Delta now={m.cases_with_telemetry_errors} before={pm?.cases_with_telemetry_errors} unit="" upIsGood={false} since={since} />
        </Tile>
        <Tile label="Cases flagged by the harness" value={num(m.cases_with_flags)}>
          <Delta now={m.cases_with_flags} before={pm?.cases_with_flags} unit="" upIsGood={false} since={since} />
        </Tile>
      </div>

      <div className="two-col">
        <div className="card">
          <h3>Verdicts</h3>
          <VerdictSplit counts={m.verdict_counts} />
          <p className="muted rules">
            Counted as passed: {rules.pass.join(", ")}. Counted as failed: {rules.fail.join(", ")}. Any other verdict
            is counted as other.
          </p>
          {notes.length > 0 && (
            <>
              <h3 className="spaced">Notes on the log files</h3>
              <ul className="plain">
                {notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="card">
          <h3>Execution</h3>
          {execution ? (
            <dl className="kv">
              {Object.entries(execution).map(([k, v]) => (
                <div key={k} className="kv-pair">
                  <dt>{k.replace(/_/g, " ")}</dt>
                  <dd>{show(v)}</dd>
                </div>
              ))}
              <div className="kv-pair">
                <dt>duration</dt>
                <dd>{duration(m.duration_s)}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">No execution file was found for this run.</p>
          )}
          {run.facts.baseline && (
            <details>
              <summary>VUI baseline</summary>
              <pre>{JSON.stringify(run.facts.baseline, null, 2)}</pre>
            </details>
          )}
        </div>
      </div>
    </section>
  );
}

function TrendHeadline({ t }: { t: Report["trend"]["summary"] }) {
  if (t.status !== "ok" || !t.previous_stamp) return null;
  const signed = (n: number | null, digits = 0) => (n === null ? "–" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${num(Math.abs(n), digits)}`);
  const word = { improving: "Improving", declining: "Declining", stable: "No change" }[t.direction ?? "stable"];
  return (
    <div className="card">
      <h3>Latest run vs {stampShort(t.previous_stamp)}</h3>
      <p>
        <strong>{word}.</strong> Pass rate {signed(t.pass_rate_change_pts, 1)} pts, passed {signed(t.passed_change)},
        failed {signed(t.failed_change)}.
      </p>
      {t.newly_failing.length > 0 && (
        <>
          <h5>Now failing</h5>
          <ul>
            {t.newly_failing.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </>
      )}
      {t.newly_passing.length > 0 && (
        <>
          <h5>Now passing</h5>
          <ul>
            {t.newly_passing.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function TrendSection({
  report,
  selected,
  onSelect,
}: {
  report: Report;
  selected: string;
  onSelect: (stamp: string) => void;
}) {
  const points = report.trend.points;
  const verdicts = orderVerdicts(points.flatMap((p) => Object.keys(p.verdict_counts)));
  if (points.length < 2) {
    return (
      <section aria-labelledby="trend-h">
        <h2 id="trend-h">Trend across runs</h2>
        <p className="card muted">
          {report.trend.summary.note} Charts and verdict changes appear here once a second run is added.
        </p>
      </section>
    );
  }
  return (
    <section aria-labelledby="trend-h">
      <h2 id="trend-h">Trend across runs</h2>
      <TrendHeadline t={report.trend.summary} />
      <div className="card">
        <h3>Pass rate per run</h3>
        <MetricOverRuns points={points} value={(p: TrendPoint) => p.pass_rate_pct} unit="%" digits={1} max={100} label="Pass rate per run" />
      </div>
      <div className="card">
        <h3>Cases per run, by verdict</h3>
        <p className="muted">Select a column to show that run.</p>
        <VerdictsOverRuns points={points} selected={selected} onSelect={onSelect} />
      </div>
      <div className="two-col">
        <div className="card">
          <h3>Average latency per run</h3>
          <MetricOverRuns points={points} value={(p: TrendPoint) => p.avg_latency_ms} unit=" ms" label="Average latency per run" />
        </div>
        <div className="card">
          <h3>Average similarity per run</h3>
          <MetricOverRuns
            points={points}
            value={(p: TrendPoint) => p.avg_similarity_pct}
            unit="%"
            digits={1}
            label="Average similarity per run"
          />
        </div>
      </div>

      <div>
        <div className="card">
          <h3>
            Verdict changes <span className="count">{report.trend.changes.length}</span>
          </h3>
          {report.trend.changes.length === 0 ? (
            <p className="muted">No case changed verdict between runs.</p>
          ) : (
            <ul className="changes">
              {[...report.trend.changes].reverse().map((c, i) => (
                <li key={i}>
                  <div>{c.case_key}</div>
                  <div className="change-line">
                    <VerdictBadge verdict={c.from_verdict} />
                    <span aria-label="changed to">→</span>
                    <VerdictBadge verdict={c.to_verdict} />
                    <span className="muted">
                      {stampShort(c.from_stamp)} to {stampShort(c.to_stamp)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Run history</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Sheet</th>
                <th className="numeric">Cases</th>
                <th className="numeric">Passed</th>
                <th className="numeric">Failed</th>
                <th className="numeric">Pass rate</th>
                {verdicts.map((v) => (
                  <th key={v} className="numeric">
                    {v}
                  </th>
                ))}
                <th className="numeric">Avg similarity</th>
                <th className="numeric">Avg latency</th>
                <th className="numeric">Telemetry errors</th>
                <th className="numeric">Flagged</th>
              </tr>
            </thead>
            <tbody>
              {[...points].reverse().map((p) => (
                <tr key={p.stamp} className={p.stamp === selected ? "is-open" : undefined} onClick={() => onSelect(p.stamp)}>
                  <td>
                    <button className="link" onClick={() => onSelect(p.stamp)}>
                      {stampLong(p.stamp)}
                    </button>
                  </td>
                  <td>{p.sheet ?? "–"}</td>
                  <td className="numeric">{num(p.cases_total)}</td>
                  <td className="numeric">{num(p.passed)}</td>
                  <td className="numeric">{num(p.failed)}</td>
                  <td className="numeric">{p.pass_rate_pct === null ? "–" : `${num(p.pass_rate_pct, 1)}%`}</td>
                  {verdicts.map((v) => (
                    <td key={v} className="numeric">
                      {p.verdict_counts[v] ?? 0}
                    </td>
                  ))}
                  <td className="numeric">{p.avg_similarity_pct === null ? "–" : `${num(p.avg_similarity_pct, 1)}%`}</td>
                  <td className="numeric">{p.avg_latency_ms === null ? "–" : `${num(p.avg_latency_ms)} ms`}</td>
                  <td className="numeric">{p.cases_with_telemetry_errors}</td>
                  <td className="numeric">{p.cases_with_flags}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function Dashboard({ report, stale }: { report: Report; stale: string | null }) {
  const runs = report.runs;
  const latest = runs[runs.length - 1].stamp;
  const [picked, setPicked] = useState<string | null>(null); // null follows the latest run
  const [verdict, setVerdict] = useState("");
  const [query, setQuery] = useState("");

  const stamp = picked && runs.some((r) => r.stamp === picked) ? picked : latest;
  const index = runs.findIndex((r) => r.stamp === stamp);
  const run = runs[index];
  const verdicts = orderVerdicts(run.facts.cases.map((c) => c.assertion.verdict ?? "(no verdict)"));
  const activeVerdict = verdicts.includes(verdict) ? verdict : "";

  /** Show one case: switch to its run and narrow the case table to it. */
  const pickCase = (caseId: string) => {
    for (const r of runs) {
      const found = r.facts.cases.find((c) => c.case_id === caseId);
      if (!found) continue;
      setPicked(r.stamp);
      setVerdict("");
      setQuery(found.utterance ?? "");
      document.getElementById("cases-h")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
  };

  const cases = useMemo(() => {
    const q = query.trim().toLowerCase();
    return run.facts.cases.filter((c) => {
      if (activeVerdict && (c.assertion.verdict ?? "(no verdict)") !== activeVerdict) return false;
      if (!q) return true;
      return [c.utterance, c.category, c.assertion.expected, c.assertion.actual, String(c.excel_row)]
        .filter(Boolean)
        .some((t) => t!.toLowerCase().includes(q));
    });
  }, [run, activeVerdict, query]);

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Execution report</h1>
          <p className="muted">
            {runs.length} run{runs.length > 1 ? "s" : ""} · updated {localTime(report.updated_at)}
            {stale ? " · could not refresh, showing the last loaded report" : " · refreshes automatically"}
          </p>
        </div>
      </header>

      <section aria-labelledby="all-h">
        <h2 id="all-h">All runs</h2>
        <div className="tiles">
          <Tile label="Runs" value={num(report.summary.runs_total)} note={`${num(report.summary.runs_completed)} completed`} />
          <Tile label="Cases executed" value={num(report.summary.cases_executed)} />
          <Tile label="Passed" value={num(report.summary.passed)} />
          <Tile
            label="Failed"
            value={num(report.summary.failed)}
            note={report.summary.other > 0 ? `${num(report.summary.other)} other` : undefined}
          />
          <Tile label="Pass rate" value={report.summary.pass_rate_pct === null ? "–" : `${num(report.summary.pass_rate_pct, 1)}%`} />
        </div>
      </section>

      <div className="filters">
        <label>
          Run
          <select value={picked ?? ""} onChange={(e) => setPicked(e.target.value || null)}>
            <option value="">Latest ({stampLong(latest)})</option>
            {[...runs].reverse().map((r) => (
              <option key={r.stamp} value={r.stamp}>
                {stampLong(r.stamp)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <RunSection run={run} previous={index > 0 ? runs[index - 1] : undefined} rules={report.outcome_rules} />

      <section aria-labelledby="cases-h">
        <h2 id="cases-h">
          Cases{" "}
          <span className="count">
            {cases.length === run.facts.cases.length ? cases.length : `${cases.length} of ${run.facts.cases.length}`}
          </span>
        </h2>
        <div className="filters">
        <label>
          Verdict
          <select value={activeVerdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="">All verdicts</option>
            {verdicts.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="grow">
          Search cases
          <input type="search" value={query} placeholder="Utterance, expected or actual text" onChange={(e) => setQuery(e.target.value)} />
        </label>
        </div>
        <div className="card flush">
          <CaseTable run={run} cases={cases} history={report.trend.case_history} />
        </div>
      </section>

      <TrendSection report={report} selected={stamp} onSelect={setPicked} />

      <AiAnalytics report={report} run={run} onSelectRun={setPicked} onPickCase={pickCase} />

      <section aria-labelledby="prov-h">
        <h2 id="prov-h">Where the values come from</h2>
        <div className="card">
          <ul className="plain">
            <li>
              <strong>Recorded results</strong> (verdicts, texts, similarity, latency, stimulus, timeline, DLT) are
              copied from the log files by a parser. No model is involved.
            </li>
            <li>
              <strong>Totals, pass and fail counts, and averages</strong> are calculated from the recorded results.
              Pass and fail follow the verdict lists shown under Verdicts; the verdict itself is never changed.
            </li>
            <li>
              <AiTag>AI</AiTag> panels and the AI analytics section are commentary from the Bedrock model, or counts
              of its labels. They are stored separately and cannot change a recorded result.
            </li>
          </ul>
          <details>
            <summary>
              Source files of this run <span className="count">{run.sources.length}</span>
            </summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <th className="numeric">Bytes</th>
                    <th>SHA-256</th>
                  </tr>
                </thead>
                <tbody>
                  {run.sources.map((s) => (
                    <tr key={s.path}>
                      <td>{s.path}</td>
                      <td className="numeric">{num(s.bytes)}</td>
                      <td>
                        <code>{s.sha256}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">
              Run <code>pheme-report verify</code> to re-read the logs and compare them with this report.
            </p>
          </details>
        </div>
      </section>
    </>
  );
}

export default function App() {
  const state = useReport();
  if (state.kind === "loading") return <main className="page" />;
  if (state.kind === "missing" || state.report.runs.length === 0) {
    return (
      <main className="page">
        <h1>Execution report</h1>
        <div className="card">
          <p>
            {state.kind === "missing"
              ? "No report was found yet."
              : "The report has no runs yet: the logs folder holds no execution files."}
          </p>
          <p className="muted">
            Build it from the project folder with <code>uv run pheme-report build</code>. This page picks it up on its
            own.
          </p>
        </div>
      </main>
    );
  }
  return (
    <main className="page">
      <Dashboard report={state.report} stale={state.stale} />
    </main>
  );
}
