import React, { useState, useEffect, useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { TrendingUp } from 'lucide-react';
import { buildPerformanceSeries, downsampleSeries, ALL_COMPONENTS } from '../../utils/portfolioTimeSeries';
import { resolutionForDays } from '../../utils/resolution';
import { timeSeriesOptions, SERIES, INK } from '../../utils/chartTheme';
import { formatSignedPercent } from '../../utils/format';
import PerformanceExplainer from './PerformanceExplainer';
import '../ChartContainer.css';

const BENCHMARKS = [
  { key: 'SPY', label: 'S&P 500 (SPY)' },
  { key: 'URTH', label: 'MSCI World (URTH)' },
];

const COMPONENT_OPTIONS = [
  { key: 'stocks', label: 'Stocks' },
  { key: 'bonds', label: 'Bonds' },
  { key: 'dividends', label: 'Dividends' },
  { key: 'selloff', label: 'Selloff' },
];

export default function PerformanceChart({ valueSeries, cashDeposits, apiBase }) {
  const [benchmark, setBenchmark] = useState('SPY');
  const [benchmarkHistory, setBenchmarkHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [components, setComponents] = useState(ALL_COMPONENTS);

  const toggleComponent = (key) => setComponents((c) => ({ ...c, [key]: !c[key] }));

  // Reuses the /api/data auto-track-and-backfill path -- SPY/URTH arrive the same
  // way any other ticker does. Resolution matches the portfolio's own span so
  // both curves share a bucket size (a daily portfolio curve against monthly
  // benchmark bars would be misleading once there are years of history).
  const firstDate = valueSeries.length > 0 ? valueSeries[0].date : null;

  useEffect(() => {
    if (!firstDate) return;
    const spanDays = Math.ceil((Date.now() - new Date(firstDate).getTime()) / 86400000);
    const resolution = resolutionForDays(spanDays);
    let isMounted = true;
    setLoading(true);
    fetch(`${apiBase}/data?tickers=${benchmark}&resolution=${resolution}&limit=5000`)
      .then((res) => (res.ok ? res.json() : { data: [] }))
      .then((payload) => { if (isMounted) setBenchmarkHistory(payload.data || []); })
      .catch(() => { if (isMounted) setBenchmarkHistory([]); })
      .finally(() => { if (isMounted) setLoading(false); });
    return () => { isMounted = false; };
  }, [benchmark, apiBase, firstDate]);

  const series = useMemo(
    () => downsampleSeries(buildPerformanceSeries(valueSeries, cashDeposits, benchmarkHistory, components)),
    [valueSeries, cashDeposits, benchmarkHistory, components]
  );

  const benchLabel = BENCHMARKS.find((b) => b.key === benchmark)?.label || benchmark;

  const chartData = useMemo(() => {
    if (series.length === 0) return null;
    return {
      labels: series.map((p) => p.date),
      datasets: [
        {
          label: 'Your portfolio',
          data: series.map((p) => p.portfolioIndex - 100),
          borderColor: SERIES[0],
          backgroundColor: 'transparent',
          pointRadius: 0,
        },
        {
          // The reference line is deliberately not a palette hue: it is the
          // baseline being compared against, not a peer series.
          label: `Same money in ${benchLabel}`,
          data: series.map((p) => (p.benchmarkIndex == null ? null : p.benchmarkIndex - 100)),
          borderColor: INK.neutral,
          backgroundColor: 'transparent',
          borderDash: [5, 4],
          pointRadius: 0,
          spanGaps: true,
        },
      ],
    };
  }, [series, benchLabel]);

  const options = useMemo(() => {
    const base = timeSeriesOptions({
      formatY: (v) => `${v > 0 ? '+' : ''}${Math.round(v)}%`,
    });
    base.plugins.tooltip.callbacks.label = (ctx) =>
      ` ${ctx.dataset.label}: ${ctx.parsed.y == null ? '--' : formatSignedPercent(ctx.parsed.y)}`;
    return base;
  }, []);

  const latest = series.length > 0 ? series[series.length - 1] : null;
  const gap =
    latest && latest.benchmarkIndex != null ? latest.portfolioIndex - latest.benchmarkIndex : null;

  return (
    <>
      <div className="chart-panel panel glass">
        <div className="panel-header stacked">
          <div className="panel-header-row">
            <h3 className="panel-title">
              <TrendingUp size={16} className="title-icon-primary" />
              <span>Performance vs Benchmark</span>
            </h3>
            <div className="chart-controls">
              {gap != null && (
                <span className={`badge ${gap >= 0 ? 'badge-success' : 'badge-warning'}`}>
                  {formatSignedPercent(gap, 1)} vs {benchmark}
                </span>
              )}
              <div className="time-window-controls" role="group" aria-label="Benchmark">
                {BENCHMARKS.map((b) => (
                  <button
                    key={b.key}
                    className={`time-btn ${benchmark === b.key ? 'active' : ''}`}
                    onClick={() => setBenchmark(b.key)}
                  >
                    {b.key}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="panel-header-row">
            <span className="text-muted text-xs uppercase">Include in return</span>
            <div className="time-window-controls" role="group" aria-label="Return components">
              {COMPONENT_OPTIONS.map((c) => (
                <button
                  key={c.key}
                  className={`time-btn ${components[c.key] ? 'active' : ''}`}
                  onClick={() => toggleComponent(c.key)}
                  aria-pressed={components[c.key]}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="chart-viewport tall">
          {loading && series.length === 0 ? (
            <div className="chart-overlay-state">
              <div className="loader-ring" />
              <p className="state-text mt-4">Loading benchmark...</p>
            </div>
          ) : !chartData ? (
            <div className="chart-overlay-state">
              <p className="state-text">Not enough data yet.</p>
            </div>
          ) : (
            <div className="chart-wrapper">
              <Line data={chartData} options={options} />
            </div>
          )}
        </div>
      </div>

      <PerformanceExplainer />
    </>
  );
}
