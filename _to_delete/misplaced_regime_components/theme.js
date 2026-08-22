// Shared visual tokens. Extends open-finance/frontend/src/utils/chartTheme.js
// so the two dashboards read as one product; App.css is the authority for the
// duplicated literals, exactly as it is over there.
//
// Colour choices here were validated, not eyeballed:
//
//   * The FOUR QUADRANTS are not a categorical series. A quadrant is a region
//     of the plane, so position already carries identity and colouring the
//     marks by quadrant would double-encode it. No 4-hue categorical set
//     passes an all-pairs CVD check against this dark surface anyway -- not
//     even the four hues open-finance already ships. So the quadrants are
//     labelled background regions at low alpha, and the trajectory is a
//     single series.
//   * The FEAR/GREED scale is diverging, so it needs two hues that read as
//     opposite plus a neutral midpoint. Red/green is the intuitive choice and
//     the wrong one: emerald against rose scores deltaE 5.5 under deuteranopia.
//     Blue-to-orange scores 30.5 and is the standard CVD-safe diverging pair.
//   * The TRAJECTORY is ordered, so recency rides a single-hue ramp rather
//     than a set of distinct hues.

export const INK = {
  primary: '#f8fafc',
  secondary: '#94a3b8',
  muted: '#7c8ba1',
  axis: '#8896ab',
  grid: 'rgba(255, 255, 255, 0.05)',
  surface: '#0e1424',
  neutral: '#64748b',
};

// Diverging poles for the sentiment scale. Fear is cold, greed is hot.
export const FEAR = '#3b82f6';
export const GREED = '#ea580c';

// Five diverging steps: pole -> light -> neutral -> light -> pole. A hue at
// the midpoint would stop it reading as "nothing in particular".
export const SENTIMENT_RAMP = [FEAR, '#7ba8f7', INK.neutral, '#f0995e', GREED];

// Single hue, light to dark, for the trajectory's recency ramp.
export const TRAJECTORY_RAMP = ['#1e3a5f', '#2a5d8f', '#3b82f6', '#7ba8f7'];

// Quadrant regions. Tints only -- every one of them is labelled in the plot,
// so identity never rests on the colour.
export const QUADRANT_TINT = {
  Goldilocks: 'rgba(14, 168, 122, 0.07)',
  Reflation: 'rgba(234, 88, 12, 0.07)',
  Stagflation: 'rgba(244, 63, 94, 0.08)',
  Deflation: 'rgba(99, 102, 241, 0.07)',
};

export const QUADRANT_EDGE = {
  Goldilocks: '#0ea87a',
  Reflation: '#ea580c',
  Stagflation: '#f43f5e',
  Deflation: '#6366f1',
  Transition: INK.neutral,
};

export const FONT_SANS = 'Inter, system-ui, sans-serif';
export const FONT_MONO = "'JetBrains Mono', ui-monospace, monospace";

export const TOOLTIP = {
  backgroundColor: 'rgba(7, 10, 19, 0.95)',
  titleColor: INK.primary,
  bodyColor: INK.secondary,
  borderColor: 'rgba(255, 255, 255, 0.1)',
  borderWidth: 1,
  padding: 10,
  cornerRadius: 8,
  boxPadding: 4,
  titleFont: { family: FONT_MONO, size: 11, weight: 600 },
  bodyFont: { family: FONT_SANS, size: 12 },
};

// Colour for a 0-100 sentiment score, stepped along the diverging ramp.
export function sentimentColor(score) {
  if (score === null || Number.isNaN(score)) return INK.neutral;
  if (score < 25) return SENTIMENT_RAMP[0];
  if (score < 45) return SENTIMENT_RAMP[1];
  if (score < 55) return SENTIMENT_RAMP[2];
  if (score < 75) return SENTIMENT_RAMP[3];
  return SENTIMENT_RAMP[4];
}

// Oldest to newest along the single-hue ramp.
export function recencyColor(i, n) {
  if (n <= 1) return TRAJECTORY_RAMP[TRAJECTORY_RAMP.length - 1];
  const slot = Math.round((i / (n - 1)) * (TRAJECTORY_RAMP.length - 1));
  return TRAJECTORY_RAMP[slot];
}

export function fmtSigned(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
}

export function fmtPct(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return `${v.toFixed(digits)}%`;
}
