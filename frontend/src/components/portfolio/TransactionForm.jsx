import React, { useState } from 'react';
import { Plus, ChevronDown, ChevronUp } from 'lucide-react';

export default function TransactionForm({ holdings, onAddTransaction }) {
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [ticker, setTicker] = useState('');
  const [date, setDate] = useState(() => new Date().toISOString().substring(0, 10));
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [type, setType] = useState('BUY');
  const [formError, setFormError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    setFormError('');

    const formattedTicker = ticker.trim().toUpperCase();
    const parsedQty = parseFloat(quantity);
    const parsedPrice = parseFloat(price);

    if (!formattedTicker) return setFormError('Please provide a ticker.');
    if (isNaN(parsedQty) || parsedQty <= 0) return setFormError('Quantity must be a positive number.');
    if (isNaN(parsedPrice) || parsedPrice <= 0) return setFormError('Price must be a positive number.');
    if (!date) return setFormError('Please select a transaction date.');

    if (type === 'SELL') {
      const existingHolding = holdings.find(h => h.ticker === formattedTicker);
      const currentShares = existingHolding ? existingHolding.shares : 0;
      if (parsedQty > currentShares) return setFormError(`Insufficient shares. You only own ${currentShares} of ${formattedTicker}.`);
    }

    const newTx = {
      id: Date.now().toString(),
      ticker: formattedTicker,
      name: formattedTicker,
      date,
      quantity: parsedQty,
      price: parsedPrice,
      type
    };

    onAddTransaction(newTx);

    setTicker(''); setQuantity(''); setPrice(''); setType('BUY'); setIsFormOpen(false);
  };

  return (
    <div className="portfolio-form-panel panel glass">
      <div 
        className="panel-header expandable-header" 
        onClick={() => setIsFormOpen(!isFormOpen)}
      >
        <h3 className="panel-title">
          <Plus size={16} className="title-icon-primary" />
          <span>Log a Transaction Manually</span>
        </h3>
        <button className="expand-btn">
          {isFormOpen ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
        </button>
      </div>
      
      {isFormOpen && (
        <div className="form-collapsible-content">
          <p className="panel-desc mt-2">
            For assets that are not in the imported Trade Republic export. Existing holdings can be edited inline from their ledger row above.
          </p>
          <form onSubmit={handleSubmit} className="portfolio-form">
            <div className="form-row-type">
              <button type="button" className={`type-btn btn-buy ${type === 'BUY' ? 'active' : ''}`} onClick={() => setType('BUY')}>Buy</button>
              <button type="button" className={`type-btn btn-sell ${type === 'SELL' ? 'active' : ''}`} onClick={() => setType('SELL')}>Sell</button>
            </div>
            <div className="form-group">
              <label>Ticker or ISIN</label>
              <input type="text" value={ticker} onChange={(e) => setTicker(e.target.value)} className="form-input" required />
            </div>
            <div className="form-grid-two">
              <div className="form-group">
                <label>Quantity</label>
                <input type="number" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} className="form-input" required />
              </div>
              <div className="form-group">
                <label>Price per share (EUR)</label>
                <input type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} className="form-input" required />
              </div>
            </div>
            <div className="form-group">
              <label>Transaction date</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="form-input" required />
            </div>
            {formError && <div className="form-error-alert">{formError}</div>}
            <button type="submit" className="form-submit-btn">Add to Portfolio</button>
          </form>
        </div>
      )}
    </div>
  );
}