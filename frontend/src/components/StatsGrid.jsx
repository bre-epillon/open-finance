import React, { useMemo } from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { formatCurrency, formatSignedPercent } from '../utils/format';
import { SERIES } from '../utils/chartTheme';
import './StatsGrid.css';

// Per-asset summary of the price history currently loaded for the Research view.
//
// Note the range: these figures cover everything fetched at the current
// resolution, which is not necessarily the window the chart above is showing --
// the chart slices client-side while this reads the whole set. The labels say
// "loaded history" rather than "period" so the two can't be confused. Wiring
// the window down here is tracked in REFACTORING.md.
export default function StatsGrid({ rawData, selectedTickers, tickerColors }) {
  const stats = useMemo(() => {
    if (!rawData || rawData.length === 0 || selectedTickers.length === 0) return [];

    const byTicker = new Map();
    rawData.forEach((d) => {
      if (!byTicker.has(d.ticker)) byTicker.set(d.ticker, []);
      byTicker.get(d.ticker).push(d);
    });

    return selectedTickers
      .map((ticker) => {
        const rows = byTicker.get(ticker);
        if (!rows || rows.length === 0) return null;
        rows.sort((a, b) => a.timestamp.localeCompare(b.timestamp));

        const firstClose = rows[0].close;
        const currentClose = rows[rows.length - 1].close;
        const closes = rows.map((d) => d.close);

        return {
          ticker,
          currentClose,
          percentChange: firstClose ? ((currentClose - firstClose) / firstClose) * 100 : 0,
          maxClose: Math.max(...closes),
          minClose: Math.min(...closes),
          from: rows[0].timestamp.slice(0, 10),
          color: tickerColors[ticker] || SERIES[0],
        };
      })
      .filter(Boolean);
  }, [rawData, selectedTickers, tickerColors]);

  if (stats.length === 0) return null;

  return (
    <div className="stats-grid animate-fade-in">
      {stats.map((stat) => {
        const isPositive = stat.percentChange >= 0;
        return (
          <div
            key={stat.ticker}
            className="stat-card glass"
            style={{ '--card-accent': stat.color, '--card-accent-glow': `${stat.color}15` }}
          >
            <div className="stat-card-header">
              <div className="stat-brand">
                <div className="stat-dot" style={{ backgroundColor: stat.color }} />
                <span className="stat-ticker">{stat.ticker}</span>
              </div>
              <div className={`stat-trend ${isPositive ? 'positive' : 'negative'}`}>
                {isPositive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                <span>{formatSignedPercent(stat.percentChange)}</span>
              </div>
            </div>

            <div className="stat-main">
              <span className="stat-label">Last close</span>
              <h3 className="stat-value">{formatCurrency(stat.currentClose)}</h3>
            </div>

            <div className="stat-details">
              <div className="detail-item">
                <span className="detail-label">High</span>
                <span className="detail-value font-mono">{formatCurrency(stat.maxClose)}</span>
              </div>
              <div className="detail-divider" />
              <div className="detail-item">
                <span className="detail-label">Low</span>
                <span className="detail-value font-mono">{formatCurrency(stat.minClose)}</span>
              </div>
            </div>

            <span className="stat-footnote">Loaded history from {stat.from}</span>
          </div>
        );
      })}
    </div>
  );
}
