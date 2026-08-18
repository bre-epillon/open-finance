import React, { useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { AreaChart } from 'lucide-react';
import { downsampleSeries } from '../../utils/portfolioTimeSeries';
import '../ChartContainer.css';

export default function PortfolioEvolutionChart({ valueSeries }) {
  const series = useMemo(() => downsampleSeries(valueSeries), [valueSeries]);

  const chartData = useMemo(() => {
    if (series.length === 0) return null;
    return {
      labels: series.map((p) => p.date),
      datasets: [
        {
          label: 'Free Cash',
          data: series.map((p) => p.cash),
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6, 182, 212, 0.35)',
          stack: 'value',
          fill: true,
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: 'Bonds',
          data: series.map((p) => p.bondsValue),
          borderColor: '#eab308',
          backgroundColor: 'rgba(234, 179, 8, 0.35)',
          stack: 'value',
          fill: true,
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: 'Stocks & Funds',
          data: series.map((p) => p.stocksValue),
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.35)',
          stack: 'value',
          fill: true,
          pointRadius: 0,
          borderWidth: 1,
        },
        {
          label: 'Cumulative Interest',
          data: series.map((p) => p.cumulativeInterest),
          borderColor: '#a855f7',
          backgroundColor: 'transparent',
          borderDash: [4, 3],
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
          yAxisID: 'y1',
        },
      ],
    };
  }, [series]);

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
          label: (ctx) =>
            ` ${ctx.dataset.label}: €${ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.03)' },
        ticks: { color: '#64748b', maxTicksLimit: 10, font: { size: 9 } },
      },
      y: {
        stacked: true,
        grid: { color: 'rgba(255,255,255,0.03)' },
        ticks: { color: '#64748b', callback: (v) => `€${v}` },
      },
      y1: {
        position: 'right',
        grid: { drawOnChartArea: false },
        ticks: { color: '#a855f7', callback: (v) => `€${v}` },
      },
    },
  }), []);

  return (
    <div className="chart-panel panel glass">
      <div className="panel-header">
        <h3 className="panel-title">
          <AreaChart size={16} className="title-icon-primary" />
          <span>Portfolio Evolution</span>
        </h3>
      </div>
      <div className="chart-viewport">
        {!chartData ? (
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
  );
}
