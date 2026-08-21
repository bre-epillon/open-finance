import React, { useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { TrendingDown } from 'lucide-react';
import { buildPerformanceSeries, downsampleSeries, ALL_COMPONENTS } from '../../utils/portfolioTimeSeries';
import { buildDrawdownSeries, computeRiskStats, RISK_FREE_RATE } from '../../utils/portfolioStats';
import { timeSeriesOptions, INK } from '../../utils/chartTheme';
import { formatPercent, formatSignedPercent, formatNumber, formatMonthLabel } from '../../utils/format';
import '../ChartContainer.css';
import './RiskPanel.css';

// Drawdown and volatility are measured on the time-weighted return index, not on
// total value: a deposit lifts value without being a gain, so a value-based
// underwater curve would "recover" on every payday and never show a real
// drawdown during a stretch of steady contributions.
//
// The benchmark is irrelevant here, so this passes an empty benchmark history
// rather than duplicating PerformanceChart's fetch.

export default function RiskPanel({ valueSeries, cashDeposits }) {
  const perfSeries = useMemo(
    () => buildPerformanceSeries(valueSeries, cashDeposits, [], ALL_COMPONENTS),
    [valueSeries, cashDeposits]
  );

  const stats = useMemo(() => computeRiskStats(perfSeries), [perfSeries]);

  const drawdown = useMemo(
    () => downsampleSeries(buildDrawdownSeries(perfSeries)),
    [perfSeries]
  );

  const chartData = useMemo(() => {
    if (drawdown.length === 0) return null;
    return {
      labels: drawdown.map((p) => p.date),
      datasets: [{
        label: 'Below peak',
        data: drawdown.map((p) => p.drawdown),
        borderColor: INK.loss,
        backgroundColor: 'rgba(244, 63, 94, 0.18)',
        fill: 'origin',
        pointRadius: 0,
      }],
    };
  }, [drawdown]);

  // Single series, so no legend box: the panel title names it.
  const options = useMemo(() => {
    const base = timeSeriesOptions({
      formatY: (v) => `${Math.round(v)}%`,
      showLegend: false,
    });
    base.scales.y.max = 0;
    base.plugins.tooltip.callbacks.label = (ctx) => ` ${formatPercent(ctx.parsed.y, 2)} below peak`;
    return base;
  }, []);

  if (!stats) {
    return (
      <div className="panel glass">
        <div className="panel-header">
          <h3 className="panel-title"><TrendingDown size={16} className="title-icon-primary" /><span>Drawdown &amp; Risk</span></h3>
        </div>
        <p className="state-text">Not enough history to measure risk yet.</p>
      </div>
    );
  }

  const tiles = [
    {
      label: 'Max drawdown',
      value: formatPercent(stats.maxDrawdown, 1),
      tone: 'loss',
      note: stats.maxDrawdownTroughDate
        ? `${stats.maxDrawdownPeakDate} peak to ${stats.maxDrawdownTroughDate} trough`
        : 'No decline from peak yet',
    },
    {
      label: 'Currently below peak',
      value: formatPercent(stats.currentDrawdown, 1),
      tone: stats.currentDrawdown < -0.05 ? 'loss' : 'flat',
      note: stats.currentDrawdown > -0.05 ? 'At or near an all-time high' : 'Distance back to the previous high',
    },
    {
      label: 'Volatility (annualised)',
      value: formatPercent(stats.annualisedVol, 1),
      tone: 'flat',
      note: 'Std. dev. of daily log returns, scaled by sqrt(252)',
    },
    {
      label: 'Sharpe ratio',
      value: stats.sharpe == null ? '--' : formatNumber(stats.sharpe),
      tone: 'flat',
      note:
        stats.sharpe == null
          ? `Needs 180+ days of history (have ${stats.spanDays})`
          : `Return above ${(RISK_FREE_RATE * 100).toFixed(0)}% risk-free, per unit of volatility`,
    },
    {
      label: 'Best month',
      value: stats.bestMonth ? formatSignedPercent(stats.bestMonth.ret, 1) : '--',
      tone: 'gain',
      note: stats.bestMonth ? formatMonthLabel(`${stats.bestMonth.month}-01`) : '',
    },
    {
      label: 'Worst month',
      value: stats.worstMonth ? formatSignedPercent(stats.worstMonth.ret, 1) : '--',
      tone: 'loss',
      note: stats.worstMonth ? formatMonthLabel(`${stats.worstMonth.month}-01`) : '',
    },
    {
      label: 'Positive months',
      value: stats.positiveMonthRate == null ? '--' : formatPercent(stats.positiveMonthRate, 0),
      tone: 'flat',
      note: `${stats.monthCount} complete month${stats.monthCount === 1 ? '' : 's'} measured`,
    },
    {
      label: stats.annualisedReturn != null ? 'Return (annualised)' : 'Return (total)',
      value: formatSignedPercent(
        stats.annualisedReturn != null ? stats.annualisedReturn : stats.totalReturn,
        1
      ),
      tone: (stats.annualisedReturn ?? stats.totalReturn) >= 0 ? 'gain' : 'loss',
      note: stats.annualisedReturn != null
        ? `${formatSignedPercent(stats.totalReturn, 1)} over ${stats.spanDays} days`
        : `Too short to annualise honestly (${stats.spanDays} days)`,
    },
  ];

  return (
    <div className="panel glass">
      <div className="panel-header">
        <div className="panel-header-row">
          <h3 className="panel-title">
            <TrendingDown size={16} className="title-icon-primary" />
            <span>Drawdown &amp; Risk</span>
          </h3>
        </div>
      </div>

      <div className="risk-tiles">
        {tiles.map((t) => (
          <div key={t.label} className="risk-tile">
            <span className="risk-tile-label">{t.label}</span>
            <span className={`risk-tile-val font-mono tone-${t.tone}`}>{t.value}</span>
            <span className="risk-tile-note">{t.note}</span>
          </div>
        ))}
      </div>

      <div className="chart-viewport short">
        {chartData ? (
          <div className="chart-wrapper">
            <Line data={chartData} options={options} />
          </div>
        ) : (
          <div className="chart-overlay-state"><p className="state-text">No drawdown history.</p></div>
        )}
      </div>

      <p className="chart-note">
        The curve is percent below the running all-time high of your time-weighted
        return index &mdash; it reads 0% whenever the portfolio is at a new high.
        Deposits are removed before each day&apos;s return is measured, so funding the
        account never registers as a gain and never resets a drawdown.
      </p>
    </div>
  );
}
