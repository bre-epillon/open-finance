import React, { useMemo } from 'react';
import { Archive } from 'lucide-react';
import { formatSigned, formatPercent } from '../../utils/format';

export default function ClosedPositionsTable({ closedHoldings }) {
  const summary = useMemo(() => {
    const totalRealizedPnL = closedHoldings.reduce((sum, h) => sum + h.realizedPnL, 0);
    const winners = closedHoldings.filter((h) => h.realizedPnL >= 0).length;
    const winRate = closedHoldings.length > 0 ? (winners / closedHoldings.length) * 100 : 0;
    return { totalRealizedPnL, winners, winRate };
  }, [closedHoldings]);

  if (closedHoldings.length === 0) return null;

  return (
    <div className="holdings-panel panel glass">
      <div className="panel-header">
        <h3 className="panel-title">
          <Archive size={16} className="title-icon-primary" />
          <span>Closed Positions</span>
        </h3>
      </div>

      <div className="portfolio-summary-row cols-3 mb-4">
        <div className="summary-card glass">
          <span className="summary-card-label">Positions closed</span>
          <h2 className="summary-card-val font-mono">{closedHoldings.length}</h2>
        </div>
        <div className="summary-card glass">
          <span className="summary-card-label">Total realised gain / loss</span>
          <h2 className={`summary-card-val font-mono ${summary.totalRealizedPnL >= 0 ? 'positive' : 'negative'}`}>
            {formatSigned(summary.totalRealizedPnL)}
          </h2>
        </div>
        <div className="summary-card glass">
          <span className="summary-card-label">Win rate</span>
          <h2 className="summary-card-val font-mono">
            {formatPercent(summary.winRate, 0)} <span className="text-muted text-sm">({summary.winners}/{closedHoldings.length})</span>
          </h2>
        </div>
      </div>

      <div className="table-viewport">
        <table className="portfolio-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Asset Name</th>
              <th className="align-right text-right-pnl">Realised gain / loss</th>
            </tr>
          </thead>
          <tbody>
            {closedHoldings.map((h) => {
              const isPos = h.realizedPnL >= 0;
              return (
                <tr key={h.ticker} className="table-row">
                  <td>
                    <div className="table-ticker-cell">
                      <span className="ticker-label font-mono">{h.ticker}</span>
                    </div>
                  </td>
                  <td className="text-muted text-sm max-w-xs truncate" title={h.name}>{h.name}</td>
                  <td className={`align-right font-mono ${isPos ? 'positive' : 'negative'}`}>
                    <div className="table-pnl-cell">
                      <span>{formatSigned(h.realizedPnL)}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}