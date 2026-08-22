import React from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import { useEngine } from './hooks/useEngine.js';
import ComponentBars from './components/ComponentBars.jsx';
import RegimeCall from './components/RegimeCall.jsx';
import RegimeScatter from './components/RegimeScatter.jsx';
import SentimentGauge from './components/SentimentGauge.jsx';
import SentimentHistory from './components/SentimentHistory.jsx';
import TiltTable from './components/TiltTable.jsx';

// Two features, one page. No router until there is a third view
// (Architecture.md), and no context: the one piece of shared state comes
// straight out of useEngine and is passed down two levels at most.

export default function App() {
  const { health, regime, history, tilts, sentiment, sentimentHistory, error,
          loading, reload } = useEngine();

  return (
    <div className="app">
      <header className="app-head">
        <h1><Activity size={18} /> Regime &amp; Sentiment</h1>
        <button type="button" className="ghost-button" onClick={reload}
                disabled={loading}>
          <RefreshCw size={13} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </header>

      {health?.demo && (
        <div className="banner demo">
          <strong>Demo mode — synthetic data.</strong> Served by
          {' '}<code>scripts/demo_server.py</code>. No FRED, no yfinance, no
          QuestDB: every figure on this page is invented and none of it says
          anything about the economy.
        </div>
      )}

      {error && (
        <div className="banner">
          <strong>Cannot reach the engine.</strong> {error}
        </div>
      )}

      {loading && !regime && !sentiment && (
        <p className="state-text">Loading…</p>
      )}

      <main className="grid">
        <section className="panel span-4"><RegimeCall regime={regime} /></section>
        <section className="panel span-8">
          <RegimeScatter history={history} quadrant={regime?.quadrant} />
        </section>
        <section className="panel span-4">
          <SentimentGauge sentiment={sentiment} />
        </section>
        <section className="panel span-8">
          <SentimentHistory history={sentimentHistory} />
        </section>
        <section className="panel span-4">
          <ComponentBars sentiment={sentiment} />
        </section>
        <section className="panel span-8"><TiltTable tilts={tilts} /></section>
      </main>

      <footer className="app-foot">
        {history && <span>{history.months} months of regime history</span>}
        <span>Reads the QuestDB instance owned by open-finance.</span>
      </footer>
    </div>
  );
}
