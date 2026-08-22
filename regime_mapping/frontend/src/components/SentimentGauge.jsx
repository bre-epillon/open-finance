import React from 'react';
import { Gauge } from 'lucide-react';
import { FEAR, GREED, INK, SENTIMENT_RAMP, sentimentColor } from '../theme.js';

// The speedometer. Hand-drawn SVG rather than a Chart.js doughnut with a
// needle plugin (which is how the parked open-finance version did it): an arc
// and a needle are ~30 lines of SVG, and going through a charting library for
// them means fighting its layout to place the hero number in the middle.
//
// The arc is a DIVERGING scale -- two hues that read as opposite, with a
// neutral grey midpoint. Blue for fear, orange for greed, deliberately not
// red/green: emerald against rose scores deltaE 5.5 under deuteranopia, which
// is below even the with-secondary-encoding floor. Blue-to-orange scores 30.5.

const R = 78;             // arc radius
const CX = 110;
const CY = 104;
const STROKE = 15;
const GAP_DEG = 1.4;      // surface-coloured gap between bands

// Band upper bounds must match core.sentiment.BANDS.
const BANDS = [
  [0, 25, 'Extreme Fear'],
  [25, 45, 'Fear'],
  [45, 55, 'Neutral'],
  [55, 75, 'Greed'],
  [75, 100, 'Extreme Greed'],
];

const toRad = (deg) => (deg * Math.PI) / 180;
// 0 -> 180deg (left), 100 -> 360deg (right).
const angleFor = (score) => 180 + (Math.max(0, Math.min(100, score)) / 100) * 180;

function point(deg, radius) {
  return [CX + radius * Math.cos(toRad(deg)), CY + radius * Math.sin(toRad(deg))];
}

function arcPath(fromDeg, toDeg, radius) {
  const [x0, y0] = point(fromDeg, radius);
  const [x1, y1] = point(toDeg, radius);
  const large = toDeg - fromDeg > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${radius} ${radius} 0 ${large} 1 ${x1} ${y1}`;
}

export default function SentimentGauge({ sentiment }) {
  if (!sentiment) return <p className="state-text">No sentiment data yet.</p>;

  const score = sentiment.composite;
  const known = score !== null && score !== undefined;
  const needle = angleFor(known ? score : 50);
  const [nx, ny] = point(needle, R - 6);
  const color = sentimentColor(known ? score : NaN);

  return (
    <div className="gauge">
      <div className="panel-head">
        <h2><Gauge size={15} /> Greed &amp; Fear</h2>
        <div className="panel-meta"><span>as of {sentiment.as_of}</span></div>
      </div>

      <svg viewBox="0 0 220 132" className="gauge-svg"
           role="img"
           aria-label={`Greed and Fear index ${known ? Math.round(score) : 'unavailable'} of 100, ${sentiment.label}`}>
        {BANDS.map(([lo, hi, name], i) => (
          <path key={name}
                d={arcPath(angleFor(lo) + GAP_DEG, angleFor(hi) - GAP_DEG, R)}
                stroke={SENTIMENT_RAMP[i]} strokeWidth={STROKE} fill="none"
                strokeLinecap="butt" />
        ))}

        {/* Needle, with a surface-coloured ring at the hub so it stays
            separable from whichever band it is sitting on. */}
        {known && (
          <>
            <line x1={CX} y1={CY} x2={nx} y2={ny}
                  stroke={INK.primary} strokeWidth="2.5" strokeLinecap="round" />
            <circle cx={CX} cy={CY} r="6" fill={color}
                    stroke={INK.surface} strokeWidth="2" />
          </>
        )}

        <text x={CX - R} y={CY + 22} className="gauge-end" textAnchor="middle">0</text>
        <text x={CX + R} y={CY + 22} className="gauge-end" textAnchor="middle">100</text>
      </svg>

      {/* Hero figure: one per view, >=48px, same sans as everything else. */}
      <div className="hero">
        <span className="hero-value" style={{ color }}>
          {known ? Math.round(score) : '--'}
        </span>
        <span className="hero-label">{sentiment.label}</span>
      </div>

      <p className="caption">
        {sentiment.reading}
        {sentiment.components < sentiment.components_expected && (
          <strong>
            {' '}Built from {sentiment.components} of{' '}
            {sentiment.components_expected} components.
          </strong>
        )}
      </p>

      <ul className="scale-key" aria-hidden="true">
        <li><span className="dot" style={{ background: FEAR }} /> Fear</li>
        <li><span className="dot" style={{ background: INK.neutral }} /> Neutral</li>
        <li><span className="dot" style={{ background: GREED }} /> Greed</li>
      </ul>
    </div>
  );
}
