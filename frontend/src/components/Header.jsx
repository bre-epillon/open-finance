import React from 'react';
import { RefreshCw, Activity, Terminal } from 'lucide-react';
import './Header.css';

/**
 * App chrome: title, API connection state, and a manual refresh.
 * Data refreshes on its own every five minutes; the button is for impatience.
 */
export default function Header({
  onRefresh,
  loading,
  isApiConnected
}) {
  return (
    <header className="terminal-header glass">
      <div className="header-brand">
        <div className="logo-container">
          <Terminal className="logo-icon" size={20} />
          <div className="logo-glow" />
        </div>
        <div>
          <h1 className="header-title">LiteFi</h1>
          <p className="header-subtitle">Portfolio &amp; market data</p>
        </div>
      </div>

      <div className="header-controls">
        <div className="status-indicator">
          <span className={`status-dot ${isApiConnected ? 'active' : 'inactive'}`} />
          <span className="status-text">{isApiConnected ? 'API connected' : 'Connecting...'}</span>
          {isApiConnected && <Activity size={12} className="status-activity-icon" />}
        </div>

        <div className="control-group">
          <button
            onClick={onRefresh}
            className={`refresh-btn ${loading ? 'loading' : ''}`}
            disabled={loading}
            title="Refetch price history now"
          >
            <RefreshCw size={16} className="refresh-icon" />
            <span>Refresh</span>
          </button>
        </div>
      </div>
    </header>
  );
}
