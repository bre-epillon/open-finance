import React, { useState } from 'react';
import { Briefcase } from 'lucide-react';
import HoldingRow from './HoldingRow.jsx';

export default function ActiveHoldingsTable({ activeHoldings, priceError, onAddTransaction, onDeleteTransaction }) {
  const [expandedRow, setExpandedRow] = useState(null);

  const handleToggleRow = (ticker) => {
    setExpandedRow(expandedRow === ticker ? null : ticker);
  };

  return (
    <div className="holdings-panel panel glass">
      <div className="panel-header">
        <h3 className="panel-title">
          <Briefcase size={16} className="title-icon-primary" />
          <span>Holdings &amp; Ledger</span>
        </h3>
      </div>

      <div className="table-viewport">
        <table className="portfolio-table">
          <thead>
            <tr>
              <th className="w-10"></th>
              <th>Symbol</th>
              <th>Asset name</th>
              <th className="align-right">Quantity</th>
              <th className="align-right">Avg cost</th>
              <th className="align-right">Last close</th>
              <th className="align-right text-right-pnl">Unrealised P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {activeHoldings.map((h) => (
              <HoldingRow
                key={h.ticker}
                holding={h}
                isExpanded={expandedRow === h.ticker}
                onToggle={() => handleToggleRow(h.ticker)}
                priceError={priceError}
                onAddMiniTransaction={onAddTransaction}
                onDeleteTransaction={onDeleteTransaction}
              />
            ))}

            {activeHoldings.length === 0 && (
              <tr>
                <td colSpan="7" className="table-empty-row">
                  No open positions. Use the form at the bottom of the page to log one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}