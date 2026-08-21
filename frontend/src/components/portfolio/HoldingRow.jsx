import React, { useState } from 'react';
import { Trash2, ChevronDown, ChevronRight } from 'lucide-react';
import { formatCurrency, formatSigned, formatSignedPercent, formatQuantity, formatPrice } from '../../utils/format';

export default function HoldingRow({ holding, isExpanded, onToggle, priceError, onAddMiniTransaction, onDeleteTransaction }) {
  const [miniDate, setMiniDate] = useState(() => new Date().toISOString().substring(0, 10));
  const [miniQty, setMiniQty] = useState('');
  const [miniPrice, setMiniPrice] = useState('');
  const [miniType, setMiniType] = useState('BUY');
  const [miniFormError, setMiniFormError] = useState('');

  const isPos = holding.pnl >= 0;

  const handleSubmit = (e) => {
    e.preventDefault();
    setMiniFormError('');

    const parsedQty = parseFloat(miniQty);
    const parsedPrice = parseFloat(miniPrice);

    if (isNaN(parsedQty) || parsedQty <= 0) return setMiniFormError('Quantity must be a positive number.');
    if (isNaN(parsedPrice) || parsedPrice <= 0) return setMiniFormError('Price must be a positive number.');
    if (!miniDate) return setMiniFormError('Please select a transaction date.');

    if (miniType === 'SELL') {
      const currentShares = holding ? holding.shares : 0;
      if (parsedQty > currentShares) return setMiniFormError(`Insufficient shares.`);
    }

    const newTx = {
      id: Date.now().toString(),
      ticker: holding.ticker,
      name: holding.name,
      date: miniDate,
      quantity: parsedQty,
      price: parsedPrice,
      type: miniType
    };

    onAddMiniTransaction(newTx);
    setMiniQty(''); setMiniPrice(''); setMiniType('BUY');
  };

  return (
    <React.Fragment>
      <tr className={`table-row grouped-row ${isExpanded ? 'expanded' : ''}`} onClick={onToggle}>
        <td className="w-10 chevron-cell">
          {isExpanded ? <ChevronDown size={16} className="text-muted" /> : <ChevronRight size={16} className="text-muted" />}
        </td>
        <td>
          <div className="table-ticker-cell">
            <span className="ticker-label font-mono">{holding.ticker}</span>
          </div>
        </td>
        <td className="text-muted text-sm max-w-xs truncate" title={holding.name}>{holding.name}</td>
        <td className="align-right font-mono">{formatQuantity(holding.shares)}</td>
        <td className="align-right font-mono">{formatCurrency(holding.avgPrice)}</td>
        <td className="align-right font-mono text-muted">
          {holding.currentPrice
            ? formatPrice(holding.currentPrice)
            : priceError ? 'Fetch failed' : 'Syncing...'}
        </td>
        <td className={`align-right font-mono ${isPos ? 'positive' : 'negative'}`}>
          <div className="table-pnl-cell">
            <span>{formatSigned(holding.pnl)}</span>
            <span className="table-pnl-pct">{formatSignedPercent(holding.pnlPercent)}</span>
          </div>
        </td>
      </tr>
      
      {isExpanded && (
        <tr className="sub-table-row">
          <td colSpan="7" className="p-0">
            <div className="sub-table-container">
              <h4 className="sub-title font-mono">Ledger: {holding.name}</h4>
              <table className="mini-ledger-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th className="align-right">Quantity</th>
                    <th className="align-right">Price</th>
                    <th className="align-right">Value</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {[...holding.history].sort((a, b) => b.date.localeCompare(a.date)).map(tx => (
                    <tr key={tx.id}>
                      <td className="font-mono text-muted text-xs">{tx.date}</td>
                      <td>
                        <span className={`ledger-type-badge ${tx.type === 'BUY' ? 'type-buy' : 'type-sell'} text-xs`}>
                          {tx.type}
                        </span>
                      </td>
                      <td className="align-right font-mono text-xs">{formatQuantity(Math.abs(tx.quantity))}</td>
                      <td className="align-right font-mono text-xs">{formatCurrency(parseFloat(tx.price))}</td>
                      <td className="align-right font-mono text-xs">{formatCurrency(Math.abs(tx.quantity) * tx.price)}</td>
                      <td className="align-center">
                        <button onClick={() => onDeleteTransaction(tx.id)} className="ledger-delete-btn"><Trash2 size={12} /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="mini-transaction-form mt-4">
                <h4 className="sub-title mb-2">Register New Transaction</h4>
                <form onSubmit={handleSubmit} className="mini-form">
                  <select value={miniType} onChange={(e) => setMiniType(e.target.value)} className="mini-input">
                    <option value="BUY">BUY</option>
                    <option value="SELL">SELL</option>
                  </select>
                  <input type="number" step="any" placeholder="Qty" value={miniQty} onChange={(e) => setMiniQty(e.target.value)} className="mini-input" required />
                  <input type="number" step="any" placeholder="Price" value={miniPrice} onChange={(e) => setMiniPrice(e.target.value)} className="mini-input" required />
                  <input type="date" value={miniDate} onChange={(e) => setMiniDate(e.target.value)} className="mini-input" required />
                  <button type="submit" className="mini-submit-btn">Add</button>
                </form>
                {miniFormError && <div className="form-error-alert text-xs mt-2">{miniFormError}</div>}
              </div>
            </div>
          </td>
        </tr>
      )}
    </React.Fragment>
  );
}