import React from 'react';
import { Compass, HelpCircle } from 'lucide-react';
import { QUADRANT_EDGE, fmtSigned } from '../theme.js';

// The regime call itself, as a stat row rather than a chart. One number and a
// label is not a chart -- an eight-hue plot of two values is the most common
// way a dashboard misses its own point.

export default function RegimeCall({ regime }) {
  if (!regime) return <p className="state-text">No regime call yet.</p>;

  const color = QUADRANT_EDGE[regime.quadrant] || QUADRANT_EDGE.Transition;
  const undecided = regime.quadrant === 'Transition';

  return (
    <div className="call">
      <div className="panel-head">
        <h2><Compass size={15} /> Macro regime</h2>
        <div className="panel-meta"><span>as of {regime.as_of}</span></div>
      </div>

      <div className="call-row">
        <span className="call-chip" style={{ borderColor: color, color }}>
          {undecided && <HelpCircle size={15} />}
          {regime.quadrant}
        </span>
        <span className="call-conf">
          confidence {regime.confidence?.toFixed(2) ?? '--'}
          <span className="call-floor">
            {' '}(floor {regime.confidence_floor})
          </span>
        </span>
      </div>

      <p className="call-reading">{regime.reading}</p>

      <dl className="stat-grid">
        <Stat label="Growth Δ" value={fmtSigned(regime.growth_delta)}
              sub={`level ${fmtSigned(regime.growth_z)} · Γ ${fmtSigned(regime.growth_gamma)}`}
              note={`${regime.growth_components} inputs`} />
        <Stat label="Inflation Δ" value={fmtSigned(regime.inflation_delta)}
              sub={`level ${fmtSigned(regime.inflation_z)} · Γ ${fmtSigned(regime.inflation_gamma)}`}
              note={`${regime.inflation_components} inputs`} />
      </dl>

      {undecided && (
        <p className="caption">
          Both axes are close enough to flat that naming a quadrant would
          overstate what the data supports. The underlying signs are still in
          the trajectory chart.
        </p>
      )}
    </div>
  );
}

function Stat({ label, value, sub, note }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>
        <span className="stat-value">{value}</span>
        <span className="stat-sub">{sub}</span>
        <span className="stat-note">{note}</span>
      </dd>
    </div>
  );
}
