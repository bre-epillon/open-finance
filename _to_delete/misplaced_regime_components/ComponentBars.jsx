import React from 'react';
import { BarChart3 } from 'lucide-react';
import { INK, sentimentColor } from '../theme.js';

// The five sub-scores. All five measure THE SAME THING on the same 0-100
// scale, so this is not five categories needing five hues -- it is one measure
// across five rows. Length carries the value; the row label carries identity.
//
// Each bar is coloured by its own position on the diverging fear/greed ramp,
// which is a value scale rather than a nominal one, so it states the value
// rather than double-encoding a category.

const LABELS = {
  momentum: 'S&P 500 momentum',
  volatility: 'Volatility (VIX vs 50d)',
  safe_haven: 'Safe-haven demand',
  junk_bond: 'High-yield spread',
  breadth: 'Market breadth',
};

const ORDER = ['momentum', 'volatility', 'safe_haven', 'junk_bond', 'breadth'];

export default function ComponentBars({ sentiment }) {
  if (!sentiment) return null;

  return (
    <div className="components">
      <div className="panel-head">
        <h2><BarChart3 size={15} /> Sentiment components</h2>
      </div>

      <ul className="bar-list">
        {ORDER.map((key) => {
          const value = sentiment[key];
          const present = value !== null && value !== undefined;
          return (
            <li key={key}>
              <span className="bar-label">{LABELS[key]}</span>
              <span className="bar-track">
                {present && (
                  <span className="bar-fill"
                        style={{ width: `${Math.max(1.5, value)}%`,
                                 background: sentimentColor(value) }} />
                )}
                {/* Midpoint tick, so "is this above or below neutral" is
                    readable without measuring against the axis. */}
                <span className="bar-mid" />
              </span>
              <span className="bar-value">
                {present ? Math.round(value) : 'n/a'}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="caption">
        Each score is a percentile against its own trailing 250 trading days,
        so 50 means &ldquo;typical for the past year&rdquo;. Volatility and the
        high-yield spread are inverted, so high always means greed.
        {' '}A component reading <em>n/a</em> was dropped from the composite
        rather than filled in as neutral.
      </p>
    </div>
  );
}
