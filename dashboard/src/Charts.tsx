import { useState, type ReactNode } from "react";
import { num, orderVerdicts, stampLong, stampShort, ticks, TONE_ICON, toneOf, useWidth } from "./lib";
import type { TrendPoint } from "./types";

// ----------------------------------------------------------------------------- shared

interface Tip {
  x: number;
  y: number;
  body: ReactNode;
}

function Tooltip({ tip, width }: { tip: Tip | null; width: number }) {
  if (!tip) return null;
  const flip = tip.x > width / 2;
  return (
    <div
      className="tooltip"
      role="status"
      style={{ top: tip.y, ...(flip ? { right: width - tip.x + 12 } : { left: tip.x + 12 }) }}
    >
      {tip.body}
    </div>
  );
}

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  const tone = toneOf(verdict);
  return (
    <span className="badge">
      <span className={`badge-icon tone-${tone}`} aria-hidden="true">
        {TONE_ICON[tone]}
      </span>
      {verdict ?? "(no verdict)"}
    </span>
  );
}

const OUTCOME: Record<string, { tone: string; label: string }> = {
  pass: { tone: "good", label: "Passed" },
  fail: { tone: "critical", label: "Failed" },
  other: { tone: "neutral", label: "Other" },
};

/** Passed / Failed / Other, as counted by the report's pass and fail rules. */
export function OutcomeBadge({ outcome }: { outcome: string | undefined }) {
  const o = OUTCOME[outcome ?? "other"] ?? OUTCOME.other;
  return (
    <span className="badge">
      <span className={`badge-icon tone-${o.tone}`} aria-hidden="true">
        {TONE_ICON[o.tone as keyof typeof TONE_ICON]}
      </span>
      {o.label}
    </span>
  );
}

export function VerdictLegend({ labels }: { labels: string[] }) {
  return (
    <ul className="legend">
      {labels.map((label) => (
        <li key={label}>
          <VerdictBadge verdict={label} />
        </li>
      ))}
    </ul>
  );
}

/** Which x labels to draw so neighbours never touch. */
function labelEvery(bandWidth: number, minGap = 76): number {
  return Math.max(1, Math.ceil(minGap / Math.max(bandWidth, 1)));
}

// ---------------------------------------------------------- verdict split of one run

/** One run's cases split by verdict: a tall segmented bar, names in the legend below. */
export function VerdictSplit({ counts }: { counts: Record<string, number> }) {
  const labels = orderVerdicts(Object.keys(counts));
  const total = labels.reduce((sum, l) => sum + counts[l], 0);
  const [active, setActive] = useState<string | null>(null);
  if (total === 0) return <p className="muted">No cases in this run.</p>;
  const describe = (l: string) => `${l}: ${counts[l]} of ${total} cases (${num((counts[l] / total) * 100)}%)`;
  return (
    <div>
      <div className="segbar" role="img" aria-label={labels.map(describe).join("; ")}>
        {labels.map((label) => {
          const share = counts[label] / total;
          return (
            <div
              key={label}
              className={`seg tone-${toneOf(label)}${active === label ? " is-active" : ""}`}
              style={{ flexGrow: counts[label] }}
              tabIndex={0}
              title={describe(label)}
              onPointerEnter={() => setActive(label)}
              onPointerLeave={() => setActive(null)}
              onFocus={() => setActive(label)}
              onBlur={() => setActive(null)}
            >
              {share >= 0.08 && <span>{counts[label]}</span>}
            </div>
          );
        })}
      </div>
      <p className="segbar-readout" aria-hidden="true">
        {active ? describe(active) : `${total} cases`}
      </p>
      <VerdictLegend labels={labels} />
    </div>
  );
}

// ------------------------------------------------------- verdicts per run, over time

const M = { top: 12, right: 16, bottom: 30, left: 40 };

export interface StackSeries {
  key: string;
  label: string;
  /** CSS class that sets the fill and background of this series. */
  className: string;
}

export interface StackPoint {
  stamp: string;
  counts: Record<string, number>;
}

/** One stacked column per run. The series order is fixed, so a colour always means the same thing. */
export function StackedColumns({
  points,
  series,
  selected,
  onSelect,
  label,
  totalLabel,
  legend,
}: {
  points: StackPoint[];
  series: StackSeries[];
  selected: string;
  onSelect: (stamp: string) => void;
  label: string;
  totalLabel: string;
  legend: ReactNode;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const height = 220;
  const total = (p: StackPoint) => series.reduce((sum, s) => sum + (p.counts[s.key] ?? 0), 0);
  const yTicks = ticks(Math.max(...points.map(total)), 4, true);
  const yMax = yTicks[yTicks.length - 1];
  const plotW = Math.max(width - M.left - M.right, 0);
  const plotH = height - M.top - M.bottom;
  const band = plotW / points.length;
  const barW = Math.min(24, Math.max(4, band - 8));
  const y = (v: number) => M.top + plotH - (v / yMax) * plotH;
  const every = labelEvery(band);

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="group" aria-label={label}>
          {yTicks.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "axis" : "grid"} x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                {t}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const cx = M.left + band * i + band / 2;
            let base = 0;
            const present = series.filter((s) => p.counts[s.key]);
            const body = (
              <>
                <div className="tooltip-title">{stampLong(p.stamp)}</div>
                {present.map((s) => (
                  <div className="tooltip-row" key={s.key}>
                    <span className={`key ${s.className}`} />
                    <strong>{p.counts[s.key]}</strong> {s.label}
                  </div>
                ))}
                <div className="tooltip-row">
                  <span className="key" />
                  <strong>{total(p)}</strong> {totalLabel}
                </div>
              </>
            );
            const show = () => setTip({ x: cx, y: M.top, body });
            return (
              <g key={p.stamp}>
                {/* Behind the bars, so hovering never tints them. */}
                <rect
                  className={`hit${p.stamp === selected ? " is-selected" : ""}`}
                  x={cx - band / 2}
                  y={M.top}
                  width={band}
                  height={plotH}
                  tabIndex={0}
                  role="button"
                  aria-label={`${stampLong(p.stamp)}: ${present.map((s) => `${p.counts[s.key]} ${s.label}`).join(", ") || `0 ${totalLabel}`}. Show this run.`}
                  onPointerEnter={show}
                  onPointerLeave={() => setTip(null)}
                  onFocus={show}
                  onBlur={() => setTip(null)}
                  onClick={() => onSelect(p.stamp)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(p.stamp);
                    }
                  }}
                />
                {present.map((s, j) => {
                  const n = p.counts[s.key];
                  const y0 = y(base);
                  const y1 = y(base + n);
                  base += n;
                  const top = j === present.length - 1;
                  // 2px surface gap between stacked segments; only the top end is rounded.
                  const yTop = y1 + (top ? 0 : 2);
                  const h = Math.max(y0 - yTop, 1);
                  const r = top ? Math.min(4, h) : 0;
                  return (
                    <path
                      key={s.key}
                      className={`bar ${s.className}`}
                      d={`M${cx - barW / 2},${yTop + h} V${yTop + r} q0,${-r} ${r},${-r} H${cx + barW / 2 - r} q${r},0 ${r},${r} V${yTop + h} Z`}
                    />
                  );
                })}
                {i % every === 0 && (
                  <text className="tick" x={cx} y={height - 10} textAnchor="middle">
                    {stampShort(p.stamp)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
      {legend}
    </div>
  );
}

export function VerdictsOverRuns({
  points,
  selected,
  onSelect,
}: {
  points: TrendPoint[];
  selected: string;
  onSelect: (stamp: string) => void;
}) {
  const labels = orderVerdicts(points.flatMap((p) => Object.keys(p.verdict_counts)));
  return (
    <StackedColumns
      points={points.map((p) => ({ stamp: p.stamp, counts: p.verdict_counts }))}
      series={labels.map((l) => ({ key: l, label: l, className: `tone-${toneOf(l)}` }))}
      selected={selected}
      onSelect={onSelect}
      label="Cases per run, split by verdict"
      totalLabel="cases"
      legend={<VerdictLegend labels={labels} />}
    />
  );
}

// --------------------------------------------------------- one measure over the runs

export function MetricOverRuns({
  points,
  value,
  unit,
  digits = 0,
  label,
  max,
}: {
  points: TrendPoint[];
  value: (p: TrendPoint) => number | null;
  unit: string;
  digits?: number;
  label: string;
  /** Fixed top of the scale, e.g. 100 for a percentage. */
  max?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 180;
  const right = 64; // room for the end label
  const data = points.map((p, i) => ({ i, p, v: value(p) })).filter((d): d is { i: number; p: TrendPoint; v: number } => d.v !== null);
  if (data.length === 0) return <p className="muted">No values recorded.</p>;

  const yTicks = ticks(max ?? Math.max(...data.map((d) => d.v)), max ? 4 : 3);
  const yMax = yTicks[yTicks.length - 1];
  const plotW = Math.max(width - M.left - right, 0);
  const plotH = height - M.top - M.bottom;
  const band = plotW / points.length;
  const x = (i: number) => M.left + band * i + band / 2;
  const y = (v: number) => M.top + plotH - (v / yMax) * plotH;
  const every = labelEvery(band);
  const last = data[data.length - 1];
  const active = hover === null ? null : (data.find((d) => d.i === hover) ?? null);
  const fmt = (v: number) => `${num(v, digits)}${unit}`;

  const nearest = (clientX: number, rect: DOMRect) => {
    const px = clientX - rect.left;
    let best = data[0];
    for (const d of data) if (Math.abs(x(d.i) - px) < Math.abs(x(best.i) - px)) best = d;
    setHover(best.i);
  };

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="group"
          aria-label={label}
          onPointerMove={(e) => nearest(e.clientX, e.currentTarget.getBoundingClientRect())}
          onPointerLeave={() => setHover(null)}
        >
          {yTicks.map((t) => (
            <g key={t}>
              <line className={t === 0 ? "axis" : "grid"} x1={M.left} x2={width - right} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                {num(t)}
              </text>
            </g>
          ))}
          {points.map(
            (p, i) =>
              i % every === 0 && (
                <text key={p.stamp} className="tick" x={x(i)} y={height - 10} textAnchor="middle">
                  {stampShort(p.stamp)}
                </text>
              ),
          )}
          {active && <line className="crosshair" x1={x(active.i)} x2={x(active.i)} y1={M.top} y2={M.top + plotH} />}
          <polyline className="line" points={data.map((d) => `${x(d.i)},${y(d.v)}`).join(" ")} />
          {data.map((d) => (
            <circle
              key={d.p.stamp}
              className="dot"
              cx={x(d.i)}
              cy={y(d.v)}
              r={active?.i === d.i ? 6 : 5}
              tabIndex={0}
              role="img"
              aria-label={`${stampLong(d.p.stamp)}: ${fmt(d.v)}`}
              onFocus={() => setHover(d.i)}
              onBlur={() => setHover(null)}
            />
          ))}
          <text className="end-label" x={x(last.i) + 10} y={y(last.v)} dy="0.32em">
            {fmt(last.v)}
          </text>
        </svg>
      )}
      <Tooltip
        width={width}
        tip={
          active && {
            x: x(active.i),
            y: M.top,
            body: (
              <>
                <div className="tooltip-title">{stampLong(active.p.stamp)}</div>
                <div className="tooltip-row">
                  <span className="key key-series" />
                  <strong>{fmt(active.v)}</strong>
                </div>
              </>
            ),
          }
        }
      />
    </div>
  );
}
