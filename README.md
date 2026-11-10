# Pheme execution report

Turns the test execution logs under `out/` into one consolidated JSON report and shows it in a React dashboard. A Claude model in Amazon Bedrock adds analysis on top of the recorded results; it cannot change them.

```
out/  ──►  pheme-report build  ──►  report/execution_report.json  ──►  dashboard
(logs)     parser + arithmetic       (the only file the dashboard reads)
           + Bedrock analysis
```

- **Report builder** (Python): parses the logs, counts pass/fail and trends, asks Bedrock for analysis, writes the JSON.
- **Dashboard** (React, Vite, TypeScript): reads the JSON and re-reads it every 5 seconds.
- **Question service** (Python, optional): answers questions typed into the dashboard, using the same JSON.

The report can be built without AI (`--no-ai`). Totals, pass/fail, trends and all case details come from the parser; only the written analysis needs Bedrock.

## Contents

- [Project layout](#project-layout)
- [Prerequisites](#prerequisites)
- [Set up](#set-up)
- [Build the report](#build-the-report)
- [Run the dashboard](#run-the-dashboard)
- [Configuration](#configuration)
- [Input: the `out/` folder](#input-the-out-folder)
- [The report JSON](#the-report-json)
- [Pass, fail and totals](#pass-fail-and-totals)
- [New logs and trends](#new-logs-and-trends)
- [AI analytics](#ai-analytics)
- [What the AI can and cannot do](#what-the-ai-can-and-cannot-do)
- [Dashboard sections](#dashboard-sections)
- [Tests and checks](#tests-and-checks)
- [Limits](#limits)
- [Troubleshooting](#troubleshooting)

## Project layout

```
out/                               execution logs (input, never modified)
report/execution_report.json       the consolidated report (output)
src/pheme_report/
  parse.py                         reads the log files into facts
  build.py                         totals, pass/fail, trend, merging with the previous report
  ai.py                            Bedrock client, prompts, and checks on the model's output
  qa.py                            question answering over the report
  server.py                        local HTTP service for the dashboard's question box
  cli.py                           the pheme-report command
dashboard/
  src/App.tsx                      page, run and trend sections
  src/AiAnalytics.tsx              AI analytics section and question box
  src/Cases.tsx                    case table and case details
  src/Charts.tsx                   charts
  src/lib.ts, types.ts             report loading, formatting, report types
  vite.config.ts                   serves report/ and forwards /api to the question service
tests/                             pytest suite with sample logs in tests/fixtures/out
.env.example                       settings template
pyproject.toml, uv.lock            Python project and locked dependencies
```

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | any recent | Python environment; it installs Python 3.12 for you |
| Node.js | 20.19 or later in the 20.x line, or 22.12 and up | Dashboard |
| pnpm | any recent (npm works too) | Dashboard dependencies |
| AWS account with Bedrock access to a Claude model | | AI analysis only; not needed with `--no-ai` |

macOS: `brew install uv node pnpm`.

## Set up

Run once from the project folder:

```bash
uv sync                            # Python dependencies into .venv
cd dashboard && pnpm install       # dashboard dependencies
cd ..
cp .env.example .env               # then edit .env, see below
```

For the AI analysis, set these in `.env`:

- `PHEME_AWS_REGION` to a region where your account can use the model, for example `us-east-1`.
- Credentials, one of:
  - `PHEME_AWS_PROFILE` to a profile from `~/.aws`, or
  - `PHEME_BEDROCK_API_KEY` to a Bedrock API key, or
  - nothing, to use the standard AWS chain (`AWS_ACCESS_KEY_ID` and related variables, SSO, instance role).
- `PHEME_MODEL` if your account uses a different model than the default `anthropic.claude-opus-5-5`.

To try the project without AWS, skip `.env` and build with `--no-ai`.

## Build the report

```bash
uv run pheme-report build              # create or update report/execution_report.json
uv run pheme-report build --no-ai      # the same without calling Bedrock
uv run pheme-report build --watch      # keep running; rebuild when new logs appear (every 30 s)
uv run pheme-report build --watch 10   # the same, checking every 10 s
uv run pheme-report verify             # re-read the logs and compare them with the report
```

| Option | Effect |
| --- | --- |
| `--out DIR` | Folder with the execution logs. Default `out` |
| `--report FILE` | Report to write. Default `report/execution_report.json` |
| `--no-ai` | Parse and count only. Existing analysis is kept if its logs are unchanged |
| `--force-ai` | Redo the analysis of every run |
| `--watch [SECONDS]` | Keep running and update the report when the logs change |

Exit codes of `build`: `0` report written or already up to date, `1` report written but an AI call failed, `2` the logs folder was not found. A failed AI call never blocks the report: the results are written, the failure is recorded in the JSON, and the next build retries.

`build` is safe to run at any time and as often as you like. See [New logs and trends](#new-logs-and-trends).

## Run the dashboard

**Development**, with live updates:

```bash
cd dashboard
pnpm dev                           # http://localhost:5174
```

The dev server serves `report/execution_report.json` directly, so a rebuilt report appears on the page within 5 seconds, without a reload.

**Question box.** The "Ask about the report" box needs the question service in a second terminal:

```bash
uv run pheme-report serve          # http://127.0.0.1:8787
```

It listens on localhost only. The dashboard's dev and preview servers forward `/api` to it, so the AWS credentials stay in that process and never reach the browser. If you change the port (`--port 9000`), start the dashboard with `PHEME_API_PORT=9000 pnpm dev`. The rest of the dashboard works without this service.

**Production build:**

```bash
cd dashboard
pnpm build                         # typecheck, then build into dashboard/dist
pnpm preview                       # serve dist on http://localhost:5174
```

`pnpm build` copies the current report into `dist/` as a snapshot. To keep a deployed dashboard current, copy the new `execution_report.json` into the served folder after each `pheme-report build`; the page picks it up on its own. A static host has no `/api`, so the question box stays disabled there unless you put a proxy to `pheme-report serve` in front.

**A typical session** uses three terminals:

```bash
uv run pheme-report build --watch      # 1: keeps the report current
uv run pheme-report serve              # 2: optional, for the question box
cd dashboard && pnpm dev               # 3: the dashboard
```

## Configuration

Settings are read from `.env` in the project folder. Variables already set in the shell take precedence.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PHEME_AWS_REGION` | standard AWS chain | AWS region for Bedrock |
| `PHEME_AWS_PROFILE` | standard AWS chain | Profile from `~/.aws` |
| `PHEME_BEDROCK_API_KEY` | empty | Bedrock API key; empty signs requests with your AWS credentials |
| `PHEME_MODEL` | `anthropic.claude-opus-5-5` | Bedrock model id; must start with `anthropic.` |
| `PHEME_EFFORT` | `medium` | How much reasoning the model spends: `low`, `medium`, `high` |
| `PHEME_PASS_VERDICTS` | `PASS,PASSED,MATCH,EXACT,OK,CLOSE` | Verdicts counted as passed |
| `PHEME_FAIL_VERDICTS` | `MISMATCH,FAIL,FAILED,ERROR,TIMEOUT` | Verdicts counted as failed |

The dashboard reads two variables from the shell when it starts:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PHEME_REPORT_DIR` | `../report` | Folder holding `execution_report.json` |
| `PHEME_API_PORT` | `8787` | Port of `pheme-report serve` |

## Input: the `out/` folder

The builder groups files into runs by the timestamp in their names (`<stamp>`, for example `20261110_120000`).

```
out/
  execution_<stamp>.json                     run metadata: outcome, sheet, selected, completed, times
  vui_baseline_<stamp>.json                  bench baseline
  run_<stamp>_<name>/logs/<case>.log         one result log per case: stimulus, expected, actual, verdict,
                                             similarity, latency, telemetry errors, timeline
  run_<stamp>_<name>/logs/<case>.export.log  telemetry export of the case (JSON)
  run_<stamp>_<name>/dlt/case_<row>.json     DLT capture of the case (JSON), linked to the case by excel row
```

Details that matter:

- A run can span several `run_<stamp>_*` folders; all of them are read.
- A `<-- note` at the end of a log line (for example `<-- MISMATCH, bench did not keep the values`) is recorded as a harness flag on that case.
- Sections the parser does not know are kept as raw lines, and every case keeps its original log text.
- A file that cannot be parsed is listed under the run's `parse_warnings`; the build continues.
- The builder never writes to `out/`.

## The report JSON

One file, `report/execution_report.json`, holds everything the dashboard shows.

| Section | Content |
| --- | --- |
| `summary` | Totals across all runs, and the same for the latest run |
| `outcome_rules` | The verdict lists used for pass and fail |
| `runs[]` | One entry per run, see below |
| `trend` | One data point per run, each case's history, verdict changes, flaky cases, failing streaks |
| `ai_trend` | Model notes on the trend |
| `ai_analytics` | Model output that spans runs: cause counts, change explanations, flaky-case analysis |
| `created_at`, `updated_at`, `schema_version`, `policy` | Bookkeeping |

Each run has separate layers, so it is always clear where a value came from:

| Layer | Where it comes from |
| --- | --- |
| `runs[].facts` | Copied from the log files by the parser. No model is involved. `execution`, `baseline`, and per case: verdict, expected and actual text, similarity, latency, stimulus, flags, telemetry errors, timeline, export events, DLT messages, original log text |
| `runs[].computed` | Arithmetic over the facts: `metrics` (counts, pass/fail, averages), `case_outcomes`, and `consistency` notes where the files disagree with each other |
| `runs[].ai` | Model analysis: `cases` (likely cause, explanation, evidence, next step), `failure_groups`, `summary` |
| `runs[].sources` | Path, size and SHA-256 of every file read for the run |
| `runs[].facts_sha256` | Hash of the run's facts |

## Pass, fail and totals

Each case is counted as passed, failed or other from its verdict label:

| Counted as | Verdicts (default) |
| --- | --- |
| passed | `PASS`, `PASSED`, `MATCH`, `EXACT`, `OK`, `CLOSE` |
| failed | `MISMATCH`, `FAIL`, `FAILED`, `ERROR`, `TIMEOUT` |
| other | any verdict in neither list |

`CLOSE` is counted as passed by default. Change the lists with `PHEME_PASS_VERDICTS` and `PHEME_FAIL_VERDICTS` in `.env`, then build again. The verdict recorded in `facts` is never changed by these lists.

Where the numbers are:

| Field | Content |
| --- | --- |
| `summary` | `runs_total`, `runs_completed`, `cases_selected`, `cases_completed`, `cases_executed`, `passed`, `failed`, `other`, `pass_rate_pct`, and the same under `latest` |
| `runs[].computed.metrics` | The same counts for one run, plus verdict counts, similarity and latency statistics, error and flag counts |
| `runs[].computed.case_outcomes` | `pass`, `fail` or `other` for each case |
| `trend.points` | One entry per run with its counts and pass rate |

## New logs and trends

Running `build` again updates the report in place:

- A new run (a new `<stamp>` under `out/`) is parsed, analysed and added.
- Runs already in the report are re-parsed. Their analysis is reused unless their logs or the pass/fail lists changed.
- A run is analysed once its `execution_<stamp>.json` exists, so a run still in progress is not sent to the model.
- Runs whose logs were removed from `out/` stay in the report as history.
- If nothing changed, the file is not rewritten.

The `trend` section is always present, for any number of runs:

| Field | Content |
| --- | --- |
| `trend.summary` | Latest run against the one before: `direction` (`improving`, `declining`, `stable`), `pass_rate_change_pts`, `passed_change`, `failed_change`, `newly_failing`, `newly_passing` |
| `trend.points` | One entry per run |
| `trend.case_history` | Every case's verdict, outcome, similarity and latency in each run |
| `trend.changes` | Every case whose verdict changed between two runs |
| `trend.flaky_cases` | Cases whose pass/fail outcome changed 2 or more times |
| `trend.failing_streaks` | For cases failing now: how many runs in a row |

With one run, `trend.summary.status` is `single_run` and the comparison fields are `null`; with no runs it is `no_runs`. From the second run on it is `ok`. A case is matched across runs by sheet, excel row and utterance.

## AI analytics

The dashboard's AI analytics section shows the items below. Each is model commentary, or a count of the model's labels.

| In the dashboard | In the JSON | How it is produced |
| --- | --- | --- |
| Summary of the run | `runs[].ai.summary` | The model summarises the run from its metrics, groups and case analysis |
| Failed cases by likely cause, per run and across runs | `ai_analytics.causes_by_run` | Counts of the cause label the model gave each failed case (`runs[].ai.cases`) |
| Failure groups | `runs[].ai.failure_groups` | The model groups a run's failed cases that share a failure signature, so one problem is listed once |
| Why verdicts changed | `ai_analytics.changes` | For each case whose verdict changed, the model compares the logs of the two runs |
| Flaky cases | `trend.flaky_cases`, `ai_analytics.flaky` | The list is counted without a model. The model then describes what separates the passing runs from the failing ones |
| Trend notes | `ai_trend` | The model describes the trend from the per-run data points. Needs two runs |
| Ask about the report | not stored | `pheme-report serve` sends the question with a digest of the report to the model |

Cause labels: `none`, `wording_variation`, `incorrect_response`, `bench_or_stimulus_setup`, `system_under_test_error`, `telemetry_gap`, `inconclusive`.

Each piece of analysis is stored with a hash of the logs it was written for and is reused until those logs change, so a rebuild only asks the model about what is new.

## What the AI can and cannot do

The model receives the recorded results as input and returns analysis only. It cannot change a result:

- No response format has a field for a verdict or any other recorded value, and only the known analysis fields are copied out of a response.
- Analysis is accepted only for cases, changes and groups that exist; unknown ids are dropped.
- A quote the model gives as evidence is kept only if it appears word for word in the logs it refers to. Dropped quotes are counted (`evidence_dropped`).
- Analysis is stored under `ai`, `ai_trend` and `ai_analytics` and is never read back into `facts`, `computed`, `summary` or `trend`.
- Answers from the question box are not saved.
- Every source file's SHA-256 is recorded, and `pheme-report verify` re-parses the logs and reports any difference from the report.

Without AI (`--no-ai`, or no credentials) the report still holds all results, totals and trends. The AI panels then say that no analysis is available.

## Dashboard sections

| Section | Shows | Source |
| --- | --- | --- |
| All runs | Runs, cases executed, passed, failed, pass rate | `summary` |
| Run (selectable) | Tiles with change against the previous run, verdict split, execution metadata, baseline | `runs[].facts`, `runs[].computed` |
| Cases | Filterable table; each row expands to the recorded result, stimulus, timeline, DLT, history across runs, original log, and the AI analysis of that case | `runs[].facts`, `runs[].ai.cases` |
| Trend across runs | Pass rate, verdicts, latency and similarity per run; verdict changes; run history table | `trend` |
| AI analytics | See [AI analytics](#ai-analytics) | `runs[].ai`, `ai_trend`, `ai_analytics` |
| Where the values come from | Provenance note and the source files with their hashes | `runs[].sources` |

Verdict labels are shown as the harness wrote them. Every AI panel is marked and has a violet edge.

## Tests and checks

```bash
uv run pytest                      # Python tests; no AWS access needed
uv run pheme-report verify         # the report on disk against the logs on disk
cd dashboard && pnpm typecheck     # TypeScript
cd dashboard && pnpm build         # typecheck and production build
```

`verify` exits with `1` and lists the differences if a recorded result in the report does not match the logs, if a computed value does not follow from the results, or if a log file changed since the report was built.

The tests use a stand-in for the model, including one that tries to overwrite verdicts and invent evidence.

## Limits

- Export events and DLT messages are stored up to 200 per case; the total is always recorded, and `truncated` marks a capped list.
- Failure grouping covers up to 250 failed cases per run; the rest are listed as not in a group.
- Verdict changes get a model explanation when they lead into one of the latest 5 runs. Older explanations are kept.
- The flaky-case analysis looks at a case's latest 6 runs.
- A case that fails once between passing runs counts as flaky (two outcome changes).
- For a very large report, the question service sends case details for the most recent runs only and says so in its answer data (`coverage`).
- Run timestamps are shown as written in the file names, without time zone conversion.

## Troubleshooting

| What you see | Cause and fix |
| --- | --- |
| `AI analysis unavailable (... No AWS region or base URL found ...)` | Set `PHEME_AWS_REGION` in `.env` |
| `Bedrock rejected the credentials` | Check `PHEME_AWS_PROFILE` or `PHEME_BEDROCK_API_KEY`, or log in again (`aws sso login`) |
| `No access to <model> in this account/region` or `Model ... not found` | Enable the model in the Bedrock console for that region, or set `PHEME_MODEL` to one you have |
| `isn't a Bedrock model id` | `PHEME_MODEL` must start with `anthropic.` |
| Dashboard says "No report was found yet" | Run `uv run pheme-report build` from the project folder |
| "The question service is not running" | Run `uv run pheme-report serve`; check `PHEME_API_PORT` if you changed the port |
| A new run has no AI analysis and says it is waiting for `execution_<stamp>.json` | The run is still in progress, or the harness did not write that file |
| Pass and fail counts look wrong | Check `outcome_rules` in the report and the two `PHEME_*_VERDICTS` settings |
| Vite refuses to start on Node 20 | It needs 20.19 or later; check `node --version` |
