import React, { useMemo, useState } from 'react';
import { Wallet, ChevronDown, ChevronUp } from 'lucide-react';
import '../PortfolioManager.css';
import '../ChartContainer.css';

export default function CashFlowView({ cashDeposits, interestPayments }) {
  const [collapsed, setCollapsed] = useState(false);

  const totals = useMemo(() => {
    const netCashMovements = cashDeposits.reduce((sum, d) => sum + d.amount, 0);
    const investmentIncome = interestPayments
      .filter((p) => p.source === 'bond' || p.source === 'dividend')
      .reduce((sum, p) => sum + p.net_amount, 0);
    const cashInterest = interestPayments
      .filter((p) => p.source === 'cash')
      .reduce((sum, p) => sum + p.net_amount, 0);
    return { netCashMovements, investmentIncome, cashInterest };
  }, [cashDeposits, interestPayments]);

  const rows = useMemo(() => {
    const movements = cashDeposits.map((d) => ({
      id: d.id,
      date: d.date,
      type: d.amount >= 0 ? 'Deposit / Transfer' : 'Card Spend',
      label: d.description,
      amount: d.amount,
    }));
    const income = interestPayments.map((p) => ({
      id: p.id,
      date: p.date,
      type: p.source === 'bond' ? 'Bond Coupon' : p.source === 'dividend' ? 'Dividend' : 'Cash Interest',
      label: p.name || p.description,
      amount: p.net_amount,
    }));
    return [...movements, ...income].sort((a, b) => b.date.localeCompare(a.date));
  }, [cashDeposits, interestPayments]);

  const fmt = (n) => `€${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div className="cashflow-panel panel glass">
      <div className="panel-header">
        <div className="panel-header-row">
          <h3 className="panel-title">
            <Wallet size={16} className="title-icon-primary" />
            <span>Cash Flow & Interest Income</span>
          </h3>
          <button className="time-btn" onClick={() => setCollapsed((c) => !c)}>
            {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
            <span>{collapsed ? `Show ${rows.length} Transactions` : 'Collapse Transactions'}</span>
          </button>
        </div>
      </div>

      <div className="portfolio-summary-row">
        <div className="summary-card glass">
          <span className="summary-card-label">Net Cash Movements</span>
          <h2 className="summary-card-val font-mono">{fmt(totals.netCashMovements)}</h2>
        </div>
        <div className="summary-card glass">
          <span className="summary-card-label">Investment Income (Bonds + Dividends)</span>
          <h2 className="summary-card-val font-mono positive">{fmt(totals.investmentIncome)}</h2>
        </div>
        <div className="summary-card glass">
          <span className="summary-card-label">Idle Cash Interest</span>
          <h2 className="summary-card-val font-mono positive">{fmt(totals.cashInterest)}</h2>
        </div>
      </div>

      {!collapsed && (
        <div className="table-viewport">
          <table className="portfolio-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Description</th>
                <th className="align-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="font-mono">{r.date}</td>
                  <td>{r.type}</td>
                  <td>{r.label}</td>
                  <td className={`align-right font-mono ${r.amount >= 0 ? 'positive' : 'negative'}`}>
                    {r.amount >= 0 ? '+' : '-'}{fmt(r.amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
