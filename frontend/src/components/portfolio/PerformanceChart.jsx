import React, { useState, useEffect, useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { TrendingUp } from 'lucide-react';
import { buildPerformanceSeries, downsampleSeries, ALL_COMPONENTS } from '../../utils/portfolioTimeSeries';
import { resolutionForDays } from '../../utils/resolution';
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
  { key: 'selloff', label: 'Selloff Gains' },
];

export default function PerformanceChart({ valueSeries, cashDeposits, apiBase }) {
  const [benchmark, setBenchmark] = useState('SPY');
  const [benchmarkHistory, setBenchmarkHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [components, setComponents] = useState(ALL_COMPONENTS);

  const toggleComponent = (key) => setComponents((c) => ({ ...c, [key]: !c[key] }));

  // Reuses the existing /api/data auto-track-and-backfill path -- SPY/URTH get pulled
  // in the same way any other ticker does, no dedicated benchmark plumbing needed.
  // Resolution matches the portfolio's own span so both series share the same bucket
  // size (comparing a daily portfolio curve against monthly benchmark bars would be
  // misleading once the portfolio has years of history).
  useEffect(() => {
    if (valueSeries.length === 0) return;
    const spanDays = Math.ceil(
      (Date.now() - new Date(valueSeries[0].date).getTime()) / 86400000
    );
    const resolution = resolutionForDays(spanDays);
    let isMounted = true;
    setLoading(true);
    fetch(`${apiBase}/data?tickers=${benchmark}&resolution=${resolution}&limit=5000`)
      .then((res) => (res.ok ? res.json() : { data: [] }))
      .then((payload) => { if (isMounted) setBenchmarkHistory(payload.data || []); })
      .catch(() => { if (isMounted) setBenchmarkHistory([]); })
      .finally(() => { if (isMounted) setLoading(false); });
    return () => { isMounted = false; };
  }, [benchmark, apiBase, valueSeries.length]);

  const series = useMemo(
    () => downsampleSeries(buildPerformanceSeries(valueSeries, cashDeposits, benchmarkHistory, components)),
    [valueSeries, cashDeposits, benchmarkHistory, components]
  );

  const chartData = useMemo(() => {
    if (series.length === 0) return null;
    const benchName = BENCHMARKS.find((b) => b.key === benchmark)?.label || benchmark;
    return {
      labels: series.map((p) => p.date),
      datasets: [
        {
          label: 'Your Portfolio',
          data: series.map((p) => p.portfolioIndex),
          borderColor: '#10b981',
          backgroundColor: 'transparent',
          borderWidth: 2,
          pointRadius: 0,
        },
        {
          label: `If invested in ${benchName} instead`,
          data: series.map((p) => p.benchmarkIndex),
          borderColor: '#64748b',
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [5, 4],
          pointRadius: 0,
          spanGaps: true,
        },
      ],
    };
  }, [series, benchmark]);

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        labels: { color: '#94a3b8', boxWidth: 10, boxHeight: 10, padding: 15, font: { size: 11 } },
      },
      tooltip: {
        backgroundColor: '#0e1424',
        titleColor: '#f8fafc',
        bodyColor: '#e2e8f0',
        callbacks: {
          label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y != null ? (ctx.parsed.y - 100).toFixed(2) : '0.00'}%`,
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.03)' },
        ticks: { color: '#64748b', maxTicksLimit: 10, font: { size: 9 } },
      },
      y: {
        grid: { color: 'rgba(255,255,255,0.03)' },
        ticks: { color: '#64748b', callback: (v) => `${(v - 100).toFixed(0)}%` },
      },
    },
  }), []);

  return (
    <>
      <div className="chart-panel panel glass">
        <div className="panel-header">
          <div className="panel-header-row">
            <h3 className="panel-title">
              <TrendingUp size={16} className="title-icon-primary" />
              <span>Performance vs Benchmark</span>
            </h3>
            <div className="time-window-controls">
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
          <div className="panel-header-row" style={{ marginTop: '0.5rem' }}>
            <span className="text-muted text-sm">Include:</span>
            <div className="time-window-controls">
              {COMPONENT_OPTIONS.map((c) => (
                <button
                  key={c.key}
                  className={`time-btn ${components[c.key] ? 'active' : ''}`}
                  onClick={() => toggleComponent(c.key)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="chart-viewport">
          {loading && series.length === 0 ? (
            <div className="chart-overlay-state">
              <p className="state-text">Loading benchmark data...</p>
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
