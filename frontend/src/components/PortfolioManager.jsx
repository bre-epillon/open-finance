import React, { useState, useEffect, useMemo } from 'react';
import { usePortfolio } from '../hooks/usePortfolio';
import PortfolioSummary from './portfolio/PortfolioSummary';
import AllocationPanel from './portfolio/AllocationPanel';
import PortfolioEvolutionChart from './portfolio/PortfolioEvolutionChart';
import PerformanceChart from './portfolio/PerformanceChart';
import RiskPanel from './portfolio/RiskPanel';
import ActiveHoldingsTable from './portfolio/ActiveHoldingsTable';
import ClosedPositionsTable from './portfolio/ClosedPositionsTable';
import CashFlowView from './portfolio/CashFlowView';
import TransactionForm from './portfolio/TransactionForm';
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
    handleDeleteTransaction,
  } = usePortfolio(apiBase, onTrackNewTicker, trackedTickers);

  // Fetched independently of the Research chart: this needs a resolution matching
  // the portfolio's whole lifetime span, not whatever window that chart has open.
  const [priceHistory, setPriceHistory] = useState([]);

  // The request only depends on *which* tickers and *how far back* -- not on the
  // transactions array's identity. Keying the effect on a primitive stops a
  // refetch every time usePortfolio rebuilds the array (split adjustment,
  // localStorage rehydrate, a single manual entry).
  const priceRequest = useMemo(() => {
    if (transactions.length === 0) return null;
    const tickers = Array.from(new Set(transactions.map((t) => t.ticker.toUpperCase()))).sort();
    const earliestDate = transactions.reduce((min, t) => (t.date < min ? t.date : min), transactions[0].date);
    const spanDays = Math.ceil((Date.now() - new Date(earliestDate).getTime()) / 86400000);
    return `${apiBase}/data?tickers=${tickers.join(',')}&resolution=${resolutionForDays(spanDays)}&limit=5000`;
  }, [transactions, apiBase]);

  useEffect(() => {
    if (!priceRequest) return;
    let isMounted = true;
    fetch(priceRequest)
      .then((res) => (res.ok ? res.json() : { data: [] }))
      .then((payload) => { if (isMounted) setPriceHistory(payload.data || []); })
      .catch(() => { if (isMounted) setPriceHistory([]); });
    return () => { isMounted = false; };
  }, [priceRequest]);

  const valueSeries = useMemo(
    () => buildValueSeries({ transactions, bondTransactions, cashDeposits, interestPayments, priceHistory }),
    [transactions, priceHistory]
  );

  // Bonds carry no live feed and cash is not a holding, so the allocation view
  // takes both from the latest point of the value series rather than re-deriving
  // them.
  const latestPoint = valueSeries.length > 0 ? valueSeries[valueSeries.length - 1] : null;

  return (
    <div className="portfolio-manager-container animate-fade-in">
      {priceError && <div className="form-error-alert">{priceError}</div>}

      <PortfolioSummary summary={portfolioSummary} latestPoint={latestPoint} />

      {/* Order follows the questions in the order they get asked: what do I own,
          how has it grown, how does that compare, how much risk did it cost, then
          the detail tables, then the data-entry forms last -- they used to sit
          between the charts and the tables, pushing the holdings table below the
          fold for no reason. */}
      <div className="portfolio-main-stack">
        <AllocationPanel
          activeHoldings={activeHoldings}
          bondsValue={latestPoint ? latestPoint.bondsValue : 0}
          cash={latestPoint ? latestPoint.cash : 0}
        />

        <PortfolioEvolutionChart valueSeries={valueSeries} />

        <PerformanceChart valueSeries={valueSeries} cashDeposits={cashDeposits} apiBase={apiBase} />

        <RiskPanel valueSeries={valueSeries} cashDeposits={cashDeposits} />

        <ActiveHoldingsTable
          activeHoldings={activeHoldings}
          priceError={priceError}
          onAddTransaction={handleAddTransaction}
          onDeleteTransaction={handleDeleteTransaction}
        />

        <ClosedPositionsTable closedHoldings={closedHoldings} />

        <CashFlowView cashDeposits={cashDeposits} interestPayments={interestPayments} />

        <TransactionForm
          holdings={[...activeHoldings, ...closedHoldings]}
          onAddTransaction={handleAddTransaction}
        />
      </div>
    </div>
  );
}
