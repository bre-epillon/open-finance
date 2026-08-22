import React from 'react';
import { AlertTriangle, Scale } from 'lucide-react';
import { FEAR, GREED, INK, fmtPct, fmtSigned } from '../theme.js';

// Baseline vs regime-tilted All Weather weights.
//
// Two series (baseline, tilted), so a legend is mandatory -- and the pair
// passes an all-pairs CVD check. The delta column is a diverging bar: over-
// weight one way, underweight the other, nothing at the midpoint.

const SLEEVES = ['Equities', 'Long Treasuries', 'Intermediate Treasuries',
                 'Gold', 'Commodities'];

// Widest delta the bar renders at full width. Beyond this it clips rather
// than rescaling, so the bars stay comparable between regimes.
const DELTA_SCALE = 12;

export default function TiltTable({ tilts }) {
  if (!tilts) return null;
  const { baseline, tilted, delta_vs_baseline: delta } = tilts;

  return (
    <div className="tilts">
      <div className="panel-head">
        <h2><Scale size={15} /> Implied All Weather tilt</h2>
        <div className="panel-meta">
          <span>{tilts.regime}</span>
          <span>confidence {tilts.confidence?.toFixed(2) ?? '--'}</span>
        </div>
      </div>

      <ul className="legend" aria-label="Series legend">
        <li><span className="key-line" style={{ background: INK.neutral }} /> Baseline</li>
        <li><span className="key-line" style={{ background: GREED }} /> Overweight</li>
        <li><span className="key-line" style={{ background: FEAR }} /> Underweight</li>
      </ul>

      {/* Wrapped so the four columns plus the diverging bar scroll on a
          narrow viewport instead of squeezing to unreadable. */}
      <div className="table-scroll wide">
      <table className="data-table tilt-table">
        <thead>
          <tr><th>Sleeve</th><th>Baseline</th><th>Tilted</th><th>Change</th></tr>
        </thead>
        <tbody>
          {SLEEVES.map((sleeve) => {
            const d = delta[sleeve] ?? 0;
            const width = Math.min(50, (Math.abs(d) / DELTA_SCALE) * 50);
            return (
              <tr key={sleeve}>
                <td>{sleeve}</td>
                <td className="num">{fmtPct(baseline[sleeve])}</td>
                <td className="num strong">{fmtPct(tilted[sleeve])}</td>
                <td>
                  <span className="diverge">
                    <span className="diverge-mid" />
                    <span className="diverge-fill"
                          style={{
                            width: `${width}%`,
                            background: d >= 0 ? GREED : FEAR,
                            left: d >= 0 ? '50%' : `${50 - width}%`,
                          }} />
                    {/* A dash, not "+0.0": a sleeve the regime has no view
                        on should not look like a measured zero change. */}
                    <span className="diverge-value">
                      {Math.abs(d) < 0.05 ? '—' : fmtSigned(d, 1)}
                    </span>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>

      <p className="disclaimer">
        <AlertTriangle size={14} /> {tilts.disclaimer}
      </p>
    </div>
  );
}
