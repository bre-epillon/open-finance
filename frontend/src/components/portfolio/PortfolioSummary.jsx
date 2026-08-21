import React from 'react';
import { formatCurrency, formatSigned, formatSignedPercent } from '../../utils/format';

// "Net Portfolio Value" used to show equity-at-market only, with cash and bonds
// left out entirely -- so the headline figure was smaller than the account and
// did not tie to the composition chart's total height. Net worth is now its own
// tile, taken from the value series, and the equity figure is labelled as such.
export default function PortfolioSummary({ summary, latestPoint }) {
  const netWorth = latestPoint ? latestPoint.totalValue : summary.totalCurrentValue;

  return (
    <div className="portfolio-summary-row">
      <div className="summary-card glass">
        <span className="summary-card-label">Net worth</span>
        <h2 className="summary-card-val font-mono">{formatCurrency(netWorth)}</h2>
        <span className="summary-card-desc">Stocks, bonds and free cash</span>
      </div>

      <div className="summary-card glass">
        <span className="summary-card-label">Equity at market</span>
        <h2 className="summary-card-val font-mono">{formatCurrency(summary.totalCurrentValue)}</h2>
        <span className="summary-card-desc">Open stock and fund positions</span>
      </div>

      <div className="summary-card glass">
        <span className="summary-card-label">Cost basis</span>
        <h2 className="summary-card-val font-mono">{formatCurrency(summary.totalCostBasis)}</h2>
        <span className="summary-card-desc">Paid for those positions</span>
      </div>

      <div className="summary-card glass">
        <span className="summary-card-label">Unrealised P&amp;L</span>
        <h2 className={`summary-card-val font-mono ${summary.totalPnL >= 0 ? 'positive' : 'negative'}`}>
          {formatSigned(summary.totalPnL)}
        </h2>
        <span className={`pnl-percent-badge ${summary.totalPnL >= 0 ? 'pos' : 'neg'}`}>
          {formatSignedPercent(summary.totalPnLPercent)}
        </span>
      </div>
    </div>
  );
}
