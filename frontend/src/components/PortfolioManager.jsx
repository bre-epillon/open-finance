import React, { useState, useEffect, useMemo } from 'react';
import { usePortfolio } from '../hooks/usePortfolio';
import PortfolioSummary from './portfolio/PortfolioSummary';
import TransactionForm from './portfolio/TransactionForm';
import ActiveHoldingsTable from './portfolio/ActiveHoldingsTable';
import ClosedPositionsTable from './portfolio/ClosedPositionsTable';
import PortfolioEvolutionChart from './portfolio/PortfolioEvolutionChart';
import PerformanceChart from './portfolio/PerformanceChart';
import CashFlowView from './portfolio/CashFlowView';
import { buildValueSeries } from '../utils/portfolioTimeSeries';
import { resolutionForDays } from '../utils/resolution';
import bondTransactions from '../state_bonds.json';
import cashDeposits from '../cash_deposits.json';
import interestPayments from '../interest_payments.json';
import './PortfolioManager.css';

export default function PortfolioManager({ trackedTickers, apiBase, onTrackNewTicker }) {
  const {
    transactions,
    activeHoldings,
    closedHoldings,
    portfolioSummary,
    priceError,
    handleAddTransaction,
    handleDeleteTransaction
  } = usePortfolio(apiBase, onTrackNewTicker, trackedTickers);

  // Fetched independently from the Terminal chart's telemetry: this needs a resolution
  // matching the portfolio's whole lifetime span, not whatever window the Terminal
  // happens to have selected -- see utils/resolution.js.
  const [priceHistory, setPriceHistory] = useState([]);

  useEffect(() => {
    if (transactions.length === 0) return;
    const tickers = Array.from(new Set(transactions.map((t) => t.ticker.toUpperCase())));
    const earliestDate = transactions.reduce((min, t) => (t.date < min ? t.date : min), transactions[0].date);
    const spanDays = Math.ceil((Date.now() - new Date(earliestDate).getTime()) / 86400000);
    const resolution = resolutionForDays(spanDays);

    let isMounted = true;
    fetch(`${apiBase}/data?tickers=${tickers.join(',')}&resolution=${resolution}&limit=5000`)
      .then((res) => (res.ok ? res.json() : { data: [] }))
      .then((payload) => { if (isMounted) setPriceHistory(payload.data || []); })
      .catch(() => { if (isMounted) setPriceHistory([]); });
    return () => { isMounted = false; };
  }, [transactions, apiBase]);

  const valueSeries = useMemo(
    () => buildValueSeries({ transactions, bondTransactions, cashDeposits, interestPayments, priceHistory }),
    [transactions, priceHistory]
  );

  return (
    <div className="portfolio-manager-container animate-fade-in">
      {priceError && (
        <div className="form-error-alert" style={{ marginBottom: '1rem' }}>
          {priceError}
        </div>
      )}

      <PortfolioSummary summary={portfolioSummary} />

      <div className="portfolio-main-stack">
        <PortfolioEvolutionChart valueSeries={valueSeries} />

        <PerformanceChart valueSeries={valueSeries} cashDeposits={cashDeposits} apiBase={apiBase} />

        <TransactionForm
          holdings={[...activeHoldings, ...closedHoldings]}
          onAddTransaction={handleAddTransaction}
        />

        <ActiveHoldingsTable
          activeHoldings={activeHoldings}
          priceError={priceError}
          onAddTransaction={handleAddTransaction}
          onDeleteTransaction={handleDeleteTransaction}
        />

        <ClosedPositionsTable
          closedHoldings={closedHoldings}
        />

        <CashFlowView cashDeposits={cashDeposits} interestPayments={interestPayments} />
      </div>
    </div>
  );
}