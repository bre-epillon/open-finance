import React, { useMemo } from 'react';
import { Bar } from 'react-chartjs-2';
import 'chart.js/auto';
import { PieChart } from 'lucide-react';
import { computeAllocation } from '../../utils/portfolioStats';
import { horizontalBarOptions, SERIES } from '../../utils/chartTheme';
import { formatCurrency, formatPercent, formatNumber } from '../../utils/format';
import '../ChartContainer.css';
import './AllocationPanel.css';

// Asset-class colours must keep this order in the stacked bar: cash -> bonds ->
// stocks. cyan/amber/emerald clears every CVD and normal-vision gate as an
// adjacent triple; putting emerald next to cyan does not (dE 12.5, below the 15
// floor). Same order as the stacked evolution chart, so the two read together.
const CLASS_COLOR = { cash: SERIES[3], bonds: SERIES[6], stocks: SERIES[0] };
const CLASS_ORDER = ['cash', 'bonds', 'stocks'];

const MAX_BARS = 12;

export default function AllocationPanel({ activeHoldings, bondsValue, cash }) {
  const allocation = useMemo(
    () => computeAllocation(activeHoldings, bondsValue, cash),
    [activeHoldings, bondsValue, cash]
  );

  const bars = useMemo(() => {
    if (!allocation) return null;
    const { positions } = allocation;
    const shown = positions.slice(0, MAX_BARS);
    const rest = positions.slice(MAX_BARS);
    // A 13th position never gets a generated colour or its own row -- it folds
    // into "Other", which is the documented behaviour past the palette's slots.
    const rows = rest.length
      ? [...shown, {
          key: `Other (${rest.length})`,
          label: `Other (${rest.length})`,
          value: rest.reduce((s, p) => s + p.value, 0),
          weight: rest.reduce((s, p) => s + p.weight, 0),
        }]
      : shown;

    return {
      labels: rows.map((r) => r.label),
      datasets: [{
        label: 'Weight of portfolio',
        data: rows.map((r) => r.weight),
        // Bars are already sorted by magnitude and named on the category axis,
        // so colour carries no extra information: one hue, not a rainbow.
        backgroundColor: SERIES[0],
        hoverBackgroundColor: SERIES[0],
        borderRadius: 4,
        borderSkipped: 'start',
        barThickness: 12,
      }],
      values: rows.map((r) => r.value),
    };
  }, [allocation]);

  const options = useMemo(() => {
    const base = horizontalBarOptions({ formatValue: (v) => `${Math.round(v)}%` });
    base.plugins.tooltip.callbacks.label = (ctx) =>
      ` ${formatPercent(ctx.parsed.x, 1)} · ${formatCurrency(bars?.values?.[ctx.dataIndex])}`;
    return base;
  }, [bars]);

  if (!allocation) {
    return (
      <div className="panel glass">
        <div className="panel-header">
          <h3 className="panel-title"><PieChart size={16} className="title-icon-primary" /><span>Allocation</span></h3>
        </div>
        <p className="state-text">No positions to allocate yet.</p>
      </div>
    );
  }

  const classByKey = Object.fromEntries(allocation.byClass.map((c) => [c.key, c]));
  const orderedClasses = CLASS_ORDER.map((k) => classByKey[k]).filter(Boolean);

  return (
    <div className="panel glass allocation-panel">
      <div className="panel-header">
        <div className="panel-header-row">
          <h3 className="panel-title">
            <PieChart size={16} className="title-icon-primary" />
            <span>Allocation &amp; Concentration</span>
          </h3>
          <span className="text-muted text-sm font-mono">
              {formatCurrency(allocation.basis)} {allocation.basisLabel}
            </span>
        </div>
      </div>

      {/* Asset class: a single stacked bar rather than a donut. Three shares,
          read left to right, with the numbers stated directly underneath -- no
          angle estimation and no legend lookup. */}
      <div className="alloc-classbar" role="img"
        aria-label={orderedClasses.map((c) => `${c.label} ${c.weight.toFixed(1)}%`).join(', ')}>
        {orderedClasses.map((c) => (
          <div
            key={c.key}
            className="alloc-classbar-seg"
            style={{ width: `${c.weight}%`, backgroundColor: CLASS_COLOR[c.key] }}
          />
        ))}
      </div>

      <div className="alloc-class-legend">
        {orderedClasses.map((c) => (
          <div key={c.key} className="alloc-class-item">
            <span className="alloc-swatch" style={{ backgroundColor: CLASS_COLOR[c.key] }} />
            <div className="alloc-class-text">
              <span className="alloc-class-label">{c.label}</span>
              <span className="alloc-class-value font-mono">
                {formatPercent(c.weight, 1)}
                <span className="text-muted"> · {formatCurrency(c.value)}</span>
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="alloc-split">
        <div className="alloc-chart">
          <h4 className="alloc-subtitle">Position weights</h4>
          <div className="alloc-bar-wrapper" style={{ height: `${Math.max(180, bars.labels.length * 26)}px` }}>
            <Bar data={bars} options={options} />
          </div>
        </div>

        <div className="alloc-metrics">
          <h4 className="alloc-subtitle">Concentration</h4>
          <div className="alloc-metric">
            <span className="alloc-metric-label">Effective positions</span>
            <span className="alloc-metric-val font-mono">{formatNumber(allocation.effectivePositions)}</span>
            <span className="alloc-metric-note">
              of {allocation.positions.length} held. Equal weights would give {allocation.positions.length};
              a lower number means the equity book leans on fewer names than it looks like.
            </span>
          </div>
          <div className="alloc-metric">
            <span className="alloc-metric-label">Top 5 positions</span>
            <span className="alloc-metric-val font-mono">{formatPercent(allocation.top5Weight, 1)}</span>
            <span className="alloc-metric-note">of {allocation.basisLabel}.</span>
          </div>
          {allocation.largest && (
            <div className="alloc-metric">
              <span className="alloc-metric-label">Largest position</span>
              <span className="alloc-metric-val font-mono">
                {allocation.largest.label} · {formatPercent(allocation.largest.weight, 1)}
              </span>
              <span className="alloc-metric-note truncate" title={allocation.largest.name}>
                {allocation.largest.name}
              </span>
            </div>
          )}
        </div>
      </div>

      <p className="chart-note">
        Stocks and funds are marked at their latest available close; bonds are held at
        cost, since no live bond price feed is ingested. Weights are shares of{' '}
        {allocation.basisLabel} ({formatCurrency(allocation.basis)}) and sum to 100%.
        {allocation.negativeCash != null && (
          <> The cash balance is negative ({formatCurrency(allocation.negativeCash)}), so
          weights are taken against invested assets rather than net worth
          ({formatCurrency(allocation.total)}).</>
        )}
      </p>
    </div>
  );
}
