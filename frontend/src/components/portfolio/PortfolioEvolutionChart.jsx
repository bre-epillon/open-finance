import React, { useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { AreaChart } from 'lucide-react';
import { downsampleSeries } from '../../utils/portfolioTimeSeries';
import { timeSeriesOptions, SERIES } from '../../utils/chartTheme';
import { formatCurrency, formatCurrencyCompact } from '../../utils/format';
import '../ChartContainer.css';

// Stack order is fixed: cash -> bonds -> stocks. cyan/amber/emerald in that
// order clears every CVD and normal-vision separation gate as an adjacent
// triple; emerald directly beside cyan does not.
//
// The "Cumulative Interest" line that used to sit on a second right-hand y-axis
// is gone. Two y-scales on one chart make the two curves visually comparable
// when they are not, and the interest was already counted inside the cash band
// anyway -- so it was double-drawn as well as mis-scaled. Interest income now
// lives in the Cash Flow panel, where it can be read against the payments that
// produced it.
const BANDS = [
  { key: 'cash', label: 'Free cash', color: SERIES[3] },
  { key: 'bondsValue', label: 'Bonds (at cost)', color: SERIES[6] },
  { key: 'stocksValue', label: 'Stocks & funds', color: SERIES[0] },
];

function withAlpha(hex, alpha) {
  return `${hex}${alpha}`;
}

export default function PortfolioEvolutionChart({ valueSeries }) {
  const series = useMemo(() => downsampleSeries(valueSeries), [valueSeries]);

  const chartData = useMemo(() => {
    if (series.length === 0) return null;
    return {
      labels: series.map((p) => p.date),
      datasets: BANDS.map((band) => ({
        label: band.label,
        data: series.map((p) => p[band.key]),
        borderColor: band.color,
        backgroundColor: withAlpha(band.color, '59'),
        // A 2px surface-coloured line between fills keeps the bands separable
        // where two adjacent segments both get thin.
        borderWidth: 1.5,
        fill: true,
        pointRadius: 0,
        stack: 'value',
      })),
    };
  }, [series]);

  const options = useMemo(
    () => timeSeriesOptions({ formatY: formatCurrencyCompact, stacked: true }),
    []
  );

  const optionsWithFullTooltip = useMemo(() => {
    const o = { ...options };
    o.plugins = {
      ...options.plugins,
      tooltip: {
        ...options.plugins.tooltip,
        callbacks: {
          label: (ctx) => ` ${ctx.dataset.label}: ${formatCurrency(ctx.parsed.y)}`,
          footer: (items) => {
            const total = items.reduce((sum, i) => sum + i.parsed.y, 0);
            return `Total: ${formatCurrency(total)}`;
          },
        },
      },
    };
    return o;
  }, [options]);

  return (
    <div className="chart-panel panel glass">
      <div className="panel-header">
        <h3 className="panel-title">
          <AreaChart size={16} className="title-icon-primary" />
          <span>Portfolio Composition Over Time</span>
        </h3>
      </div>
      <div className="chart-viewport tall">
        {!chartData ? (
          <div className="chart-overlay-state">
            <p className="state-text">Not enough data yet.</p>
          </div>
        ) : (
          <div className="chart-wrapper">
            <Line data={chartData} options={optionsWithFullTooltip} />
          </div>
        )}
      </div>
      <p className="chart-note">
        Total height is your net worth in the account on that date. Stocks and funds are
        marked at their last available close; bonds are held at cost, since no bond price
        feed is ingested. Free cash includes interest and coupons already received.
      </p>
    </div>
  );
}
