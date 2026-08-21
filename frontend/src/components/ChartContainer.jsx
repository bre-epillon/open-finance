import React, { useMemo, useState } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { AreaChart, TrendingUp, HelpCircle } from 'lucide-react';
import { timeSeriesOptions, INK } from '../utils/chartTheme.js';
import { formatCurrencyCompact, formatCurrency, formatSignedPercent } from '../utils/format.js';
import './ChartContainer.css';

const TIME_WINDOWS = ['1M', 'YTD', '1Y', '5Y', 'All'];

// Overlaying two assets on one price axis is only meaningful when they trade at
// similar absolute levels; a 5 EUR stock beside a 500 EUR one flattens into a
// straight line. Indexed mode rebases both to 0% at the window start, which is
// the comparison actually being asked for. It is the default whenever more than
// one asset is selected.
const SCALES = [
  { key: 'indexed', label: '% change' },
  { key: 'price', label: 'Price' },
];

function windowStart(latestMs, win, earliestMs) {
  const d = new Date(latestMs);
  switch (win) {
    case '1M': return new Date(d).setMonth(d.getMonth() - 1);
    case 'YTD': return new Date(d.getFullYear(), 0, 1).getTime();
    case '1Y': return new Date(d).setFullYear(d.getFullYear() - 1);
    case '5Y': return new Date(d).setFullYear(d.getFullYear() - 5);
    default: return earliestMs;
  }
}

export default function ChartContainer({ rawData, selectedTickers, loading, tickerColors, onWindowChange }) {
  const [selectedWindow, setSelectedWindow] = useState('1Y');
  const [scaleMode, setScaleMode] = useState(null); // null = follow the selection count

  const effectiveScale = scaleMode ?? (selectedTickers.length > 1 ? 'indexed' : 'price');

  const handleSelectWindow = (win) => {
    setSelectedWindow(win);
    onWindowChange?.(win);
  };

  // One pass over rawData builds both the timestamp axis and a
  // ticker -> (timestamp -> close) lookup. The previous version called
  // rawData.find() once per point per series inside the render path, which is
  // O(points x series x rows) -- with 5,000 rows and a few tickers selected that
  // was millions of comparisons on every re-render.
  const { timestamps, closesByTicker } = useMemo(() => {
    const byTicker = new Map();
    const tsSet = new Set();
    (rawData || []).forEach((d) => {
      const ts = new Date(d.timestamp).getTime();
      tsSet.add(ts);
      let series = byTicker.get(d.ticker);
      if (!series) { series = new Map(); byTicker.set(d.ticker, series); }
      series.set(ts, d.close);
    });
    return { timestamps: [...tsSet].sort((a, b) => a - b), closesByTicker: byTicker };
  }, [rawData]);

  const visibleTimestamps = useMemo(() => {
    if (timestamps.length === 0) return [];
    const latest = timestamps[timestamps.length - 1];
    const start = Math.max(windowStart(latest, selectedWindow, timestamps[0]), timestamps[0]);
    const filtered = timestamps.filter((ts) => ts >= start && ts <= latest);
    if (filtered.length <= 500) return filtered;
    const factor = Math.ceil(filtered.length / 500);
    return filtered.filter((_, i) => i % factor === 0 || i === filtered.length - 1);
  }, [timestamps, selectedWindow]);

  const chartData = useMemo(() => {
    if (visibleTimestamps.length === 0) return null;

    const labels = visibleTimestamps.map((ts) =>
      new Date(ts).toLocaleDateString('en-GB', { year: '2-digit', month: 'short', day: 'numeric' })
    );

    const datasets = selectedTickers.map((ticker) => {
      const color = tickerColors[ticker] || INK.gain;
      const series = closesByTicker.get(ticker);
      const raw = visibleTimestamps.map((ts) => (series ? series.get(ts) ?? null : null));
      const base = raw.find((v) => v != null);

      const data =
        effectiveScale === 'indexed' && base
          ? raw.map((v) => (v == null ? null : (v / base - 1) * 100))
          : raw;

      return {
        label: ticker,
        data,
        borderColor: color,
        backgroundColor: (context) => {
          const { ctx, chartArea } = context.chart;
          if (!chartArea) return 'transparent';
          const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          gradient.addColorStop(0, `${color}22`);
          gradient.addColorStop(1, `${color}00`);
          return gradient;
        },
        fill: selectedTickers.length === 1,
        spanGaps: true,
      };
    });

    return { labels, datasets };
  }, [visibleTimestamps, selectedTickers, tickerColors, closesByTicker, effectiveScale]);

  const options = useMemo(() => {
    const isIndexed = effectiveScale === 'indexed';
    const base = timeSeriesOptions({
      formatY: isIndexed ? (v) => `${v > 0 ? '+' : ''}${Math.round(v)}%` : formatCurrencyCompact,
      showLegend: selectedTickers.length > 1,
    });
    // The tooltip wants full precision even where the axis is abbreviated.
    base.plugins.tooltip.callbacks.label = (ctx) =>
      ` ${ctx.dataset.label}: ${
        ctx.parsed.y == null ? '--' : isIndexed ? formatSignedPercent(ctx.parsed.y) : formatCurrency(ctx.parsed.y)
      }`;
    return base;
  }, [effectiveScale, selectedTickers.length]);

  const hasData = selectedTickers.length > 0 && rawData && rawData.length > 0;

  return (
    <main className="chart-panel panel glass">
      <div className="panel-header">
        <div className="panel-header-row">
          <h2 className="panel-title">
            <AreaChart size={16} className="title-icon-primary" />
            <span>Price History</span>
          </h2>

          <div className="chart-controls">
            <div className="time-window-controls" role="group" aria-label="Value scale">
              {SCALES.map((s) => (
                <button
                  key={s.key}
                  className={`time-btn ${effectiveScale === s.key ? 'active' : ''}`}
                  onClick={() => setScaleMode(s.key)}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <div className="time-window-controls" role="group" aria-label="Time window">
              {TIME_WINDOWS.map((win) => (
                <button
                  key={win}
                  className={`time-btn ${selectedWindow === win ? 'active' : ''}`}
                  onClick={() => handleSelectWindow(win)}
                >
                  {win}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="chart-viewport">
        {loading && (
          <div className="chart-overlay-state">
            <div className="loader-ring" />
            <p className="state-text mt-4">Loading price history...</p>
          </div>
        )}

        {!loading && selectedTickers.length === 0 && (
          <div className="chart-overlay-state">
            <TrendingUp size={32} className="state-icon-muted" />
            <p className="state-title">No asset selected</p>
            <p className="state-subtitle">Pick one or more assets in the sidebar to plot their curves.</p>
          </div>
        )}

        {!loading && selectedTickers.length > 0 && !hasData && (
          <div className="chart-overlay-state">
            <HelpCircle size={32} className="state-icon-warn" />
            <p className="state-title">No data in range</p>
            <p className="state-subtitle">Backfill may still be running for the selected assets.</p>
          </div>
        )}

        {!loading && chartData && hasData && (
          <div className="chart-wrapper">
            <Line data={chartData} options={options} />
          </div>
        )}
      </div>
    </main>
  );
}
