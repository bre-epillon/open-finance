import React from 'react';
import TickerSelector from './TickerSelector.jsx';
import TickerTracker from './TickerTracker.jsx';
import ChartContainer from './ChartContainer.jsx';
import StatsGrid from './StatsGrid.jsx';

// The former "Live Terminal": look up any tracked asset's price history before
// buying it. Lifted out of App.jsx so App is routing + data-fetching only.
export default function ResearchView({
  tickers,
  selectedTickers,
  tickerColors,
  rawData,
  tickersLoading,
  dataLoading,
  apiBase,
  onToggleTicker,
  onTrackSuccess,
  onWindowChange,
}) {
  return (
    <div className="dashboard-grid animate-fade-in">
      <aside className="sidebar flex flex-col gap-4">
        <TickerSelector
          tickers={tickers}
          selectedTickers={selectedTickers}
          onToggleTicker={onToggleTicker}
          loading={tickersLoading}
          tickerColors={tickerColors}
        />
        <TickerTracker onTrackSuccess={onTrackSuccess} apiBase={apiBase} />
      </aside>

      <section className="main-content flex flex-col gap-4">
        <ChartContainer
          rawData={rawData}
          selectedTickers={selectedTickers}
          loading={dataLoading}
          tickerColors={tickerColors}
          onWindowChange={onWindowChange}
        />
        <StatsGrid
          rawData={rawData}
          selectedTickers={selectedTickers}
          tickerColors={tickerColors}
        />
      </section>
    </div>
  );
}
