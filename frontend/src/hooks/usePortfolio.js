import { useState, useEffect, useMemo } from 'react';
import initialTransactions from '../parsed_transactions.json';

// Rescales any transaction that predates a stock split it hasn't been adjusted for yet.
// `adjustedSplits` is tagged per-transaction (not tracked globally) so a transaction added
// later, backdated before a split that was already processed, still gets caught next run.
export function applySplitsToTransactions(transactions, splits) {
  let changed = false;
  const next = transactions.map((tx) => {
    const applied = new Set(tx.adjustedSplits || []);
    let quantity = tx.quantity;
    let price = tx.price;
    let touched = false;

    splits.forEach((s) => {
      const key = `${s.ticker}|${s.effective_date}`;
      if (applied.has(key)) return;
      if (tx.ticker.toUpperCase() !== s.ticker.toUpperCase()) return;
      if (new Date(tx.date) >= new Date(s.effective_date)) return;

      quantity *= s.ratio;
      price /= s.ratio;
      applied.add(key);
      touched = true;
    });

    if (!touched) return tx;
    changed = true;
    return { ...tx, quantity, price, adjustedSplits: [...applied] };
  });
  return changed ? next : transactions;
}

export function usePortfolio(apiBase, onTrackNewTicker, trackedTickers) {
  const [transactions, setTransactions] = useState(() => {
    const saved = localStorage.getItem('litefi_portfolio_transactions');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed.length > 0) {
        // Map names from initial JSON to fix previously cached transactions missing the name
        const nameMap = {};
        (initialTransactions || []).forEach(t => {
          if (t.name && t.name !== t.ticker) {
            nameMap[t.ticker.toUpperCase()] = t.name;
          }
        });
        
        return parsed.map(tx => ({
          ...tx,
          name: tx.name && tx.name !== tx.ticker ? tx.name : (nameMap[tx.ticker.toUpperCase()] || tx.ticker)
        }));
      }
    }
    return initialTransactions || [];
  });

  // Persist transactions
  useEffect(() => {
    localStorage.setItem('litefi_portfolio_transactions', JSON.stringify(transactions));
  }, [transactions]);

  // Catch up on any stock split -- past or future -- recorded by the backend's corporate
  // actions ledger. Runs on every load; per-transaction tagging keeps it a no-op once caught up.
  useEffect(() => {
    let isMounted = true;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/corporate_actions`);
        if (!res.ok || !isMounted) return;
        const { data } = await res.json();
        const splits = (data || []).filter((a) => a.action_type === 'SPLIT');
        if (splits.length === 0) return;
        setTransactions((prev) => applySplitsToTransactions(prev, splits));
      } catch (err) {
        console.error('Failed to check corporate actions for splits', err);
      }
    })();
    return () => { isMounted = false; };
  }, [apiBase]);

  // Live Prices State
  const [livePrices, setLivePrices] = useState({});
  const [priceError, setPriceError] = useState('');

  const uniqueTickers = useMemo(() => {
    return Array.from(new Set(transactions.map(tx => tx.ticker.toUpperCase())));
  }, [transactions]);

  useEffect(() => {
    if (uniqueTickers.length === 0) return;
    let isMounted = true;
    const fetchPrices = async () => {
      try {
        setPriceError('');
        const res = await fetch(`${apiBase}/latest_prices?tickers=${uniqueTickers.join(',')}`);
        if (!res.ok) {
           throw new Error('Failed to fetch from API');
        }
        const data = await res.json();
        if (isMounted) setLivePrices(data);
      } catch (err) {
        console.error(err);
        if (isMounted) setPriceError('Unable to sync live market prices.');
      }
    };
    fetchPrices();
    
    const interval = setInterval(fetchPrices, 60000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [uniqueTickers, apiBase]);

  // Dynamically calculate Holdings
  const holdings = useMemo(() => {
    const map = {};

    const sortedTx = [...transactions].sort((a, b) => new Date(a.date) - new Date(b.date));

    sortedTx.forEach((tx) => {
      const sym = tx.ticker.toUpperCase();
      if (!map[sym]) {
        map[sym] = {
          ticker: sym,
          name: tx.name || sym,
          shares: 0,
          totalCost: 0,
          realizedPnL: 0,
          history: [] // store all txs for this asset
        };
      }

      const holding = map[sym];
      const qty = Math.abs(parseFloat(tx.quantity));
      const prc = parseFloat(tx.price);

      // Save name if not present and available in tx
      if (tx.name && holding.name === sym) {
         holding.name = tx.name;
      }

      holding.history.push(tx);

      if (tx.type === 'BUY') {
        holding.shares += qty;
        holding.totalCost += qty * prc;
      } else {
        holding.shares -= qty;
        const avgBuyPrice = holding.shares + qty > 0 ? (holding.totalCost / (holding.shares + qty)) : 0;
        holding.totalCost -= qty * avgBuyPrice;
        holding.realizedPnL += qty * (prc - avgBuyPrice);
      }
    });

    return Object.values(map)
      .map((holding) => {
        if (holding.shares <= 0.00001 && holding.history.length === 0) return null;

        const currentPrice = livePrices[holding.ticker] || null;
        const avgPrice = holding.shares > 0.00001 ? (holding.totalCost / holding.shares) : 0;
        const currentValue = (holding.shares > 0.00001 && currentPrice) ? holding.shares * currentPrice : holding.totalCost;
        const totalCostBasis = holding.shares > 0.00001 ? holding.shares * avgPrice : 0;
        const pnl = currentPrice ? currentValue - totalCostBasis : 0;
        const pnlPercent = totalCostBasis > 0 ? (pnl / totalCostBasis) * 100 : 0;

        // Clean up floating point precision on shares
        holding.shares = Math.abs(holding.shares) < 0.00001 ? 0 : holding.shares;

        return {
          ...holding,
          avgPrice,
          currentPrice,
          currentValue,
          totalCostBasis,
          pnl,
          pnlPercent
        };
      })
      .filter(Boolean);
  }, [transactions, livePrices]);

  const activeHoldings = useMemo(() => holdings.filter(h => h.shares > 0), [holdings]);
  const closedHoldings = useMemo(() => holdings.filter(h => h.shares <= 0), [holdings]);

  const portfolioSummary = useMemo(() => {
    let totalCostBasis = 0;
    let totalCurrentValue = 0;

    activeHoldings.forEach((h) => {
      totalCostBasis += h.totalCostBasis;
      totalCurrentValue += h.currentValue;
    });

    const totalPnL = totalCurrentValue - totalCostBasis;
    const totalPnLPercent = totalCostBasis > 0 ? (totalPnL / totalCostBasis) * 100 : 0;

    return {
      totalCostBasis,
      totalCurrentValue,
      totalPnL,
      totalPnLPercent
    };
  }, [activeHoldings]);

  const handleAddTransaction = (newTx) => {
    setTransactions((prev) => [newTx, ...prev]);
    if (onTrackNewTicker && !trackedTickers.includes(newTx.ticker)) {
      onTrackNewTicker(newTx.ticker);
    }
  };

  const handleDeleteTransaction = (id) => {
    setTransactions((prev) => prev.filter((tx) => tx.id !== id));
  };

  return {
    transactions,
    activeHoldings,
    closedHoldings,
    portfolioSummary,
    priceError,
    handleAddTransaction,
    handleDeleteTransaction
  };
}