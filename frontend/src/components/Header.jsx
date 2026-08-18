import React from 'react';
import { RefreshCw, Activity, Terminal } from 'lucide-react';
import './Header.css';

/**
 * Header Component
 * Displays the main title, subtitle, connection status, and resolution/refresh controls.
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
          <h1 className="header-title">LiteFi Terminal</h1>
          <p className="header-subtitle">High-frequency timeseries node visualizer</p>
        </div>
      </div>

      <div className="header-controls">
        <div className="status-indicator">
          <span className={`status-dot ${isApiConnected ? 'active' : 'inactive'}`} />
          <span className="status-text">{isApiConnected ? 'Node Connected' : 'Connecting...'}</span>
          {isApiConnected && <Activity size={12} className="status-activity-icon" />}
        </div>

        <div className="control-group">
          <button
            onClick={onRefresh}
            className={`refresh-btn ${loading ? 'loading' : ''}`}
            disabled={loading}
            title="Force data refresh"
          >
            <RefreshCw size={16} className="refresh-icon" />
            <span>Refresh</span>
          </button>
        </div>
      </div>
    </header>
  );
}
