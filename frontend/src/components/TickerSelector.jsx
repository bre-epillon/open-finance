import React from 'react';
import { Layers, Check } from 'lucide-react';
import './TickerSelector.css';

/**
 * The tracked-asset list. Colour is assigned by slot order from the shared
 * palette (see utils/chartTheme.js) and is the same colour the chart uses.
 */
export default function TickerSelector({
  tickers,
  selectedTickers,
  onToggleTicker,
  loading,
  tickerColors
}) {
  return (
    <div className="ticker-selector-panel panel glass">
      <div className="panel-header">
        <h2 className="panel-title">
          <Layers size={16} className="title-icon" />
          <span>Tracked Assets</span>
        </h2>
        <span className="ticker-count-badge">{selectedTickers.length} on</span>
      </div>

      <p className="panel-desc">
        Select assets to overlay. With more than one selected the chart switches to percent change, so different price levels stay comparable.
      </p>

      {loading && tickers.length === 0 ? (
        <div className="selector-loading-skeleton">
          <div className="skeleton-item" />
          <div className="skeleton-item" />
          <div className="skeleton-item" />
        </div>
      ) : (
        <div className="ticker-list">
          {tickers.map((ticker) => {
            const isSelected = selectedTickers.includes(ticker);
            const color = tickerColors[ticker] || '#10b981';
            
            return (
              <button
                key={ticker}
                onClick={() => onToggleTicker(ticker)}
                className={`ticker-item-btn ${isSelected ? 'selected' : ''}`}
                style={{
                  '--ticker-accent-color': color,
                  '--ticker-bg-color': isSelected ? `${color}12` : 'transparent',
                  '--ticker-border-color': isSelected ? `${color}40` : 'var(--border-color)'
                }}
              >
                <div className="ticker-item-left">
                  <div className="ticker-color-dot" style={{ backgroundColor: color }} />
                  <span className="ticker-symbol">{ticker}</span>
                </div>
                <div className="ticker-item-right">
                  {isSelected && <Check size={14} className="check-icon" style={{ color: color }} />}
                </div>
              </button>
            );
          })}
          
          {tickers.length === 0 && (
            <div className="empty-tickers-message">
              No assets tracked yet. Add one below.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
