// Shared Chart.js theme.
//
// The three chart components each carried their own ~50-line `options` object,
// near-identical but drifting (different grid greys, different tick sizes, one
// with tooltips configured and one without). This is the single source.
//
// Values mirror the CSS custom properties in App.css. They are duplicated as
// literals rather than read from getComputedStyle because Chart.js needs a
// concrete colour at dataset-build time and a canvas has no cascade -- but the
// two lists must be kept in step. App.css is the authority.

export const SERIES = [
  '#0ea87a', // 1 emerald
  '#6366f1', // 2 indigo
  '#ea580c', // 3 orange
  '#0891b2', // 4 cyan
  '#f43f5e', // 5 rose
  '#3b82f6', // 6 blue
  '#b3860b', // 7 amber
  '#a855f7', // 8 purple
];

export const INK = {
  primary: '#f8fafc',
  secondary: '#94a3b8',
  muted: '#7c8ba1',
  axis: '#8896ab',
  grid: 'rgba(255, 255, 255, 0.05)',
  surface: '#0e1424',
  gain: '#34d399',
  loss: '#fb7185',
  neutral: '#64748b',
};

const FONT_SANS = "Inter, system-ui, sans-serif";
const FONT_MONO = "'JetBrains Mono', ui-monospace, monospace";

// Colour follows the entity, not its rank: a ticker keeps its colour when other
// tickers are deselected. Hashing the symbol (rather than indexing the current
// selection) is what makes that true.
export function colorForKey(key, fallbackIndex = 0) {
  if (!key) return SERIES[fallbackIndex % SERIES.length];
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return SERIES[hash % SERIES.length];
}

// Assigns each key a distinct slot in fixed order where possible, falling back
// to hashing past slot 8. Used for the tracked-ticker legend, where "all eight
// visible at once and all different" matters more than stability.
export function buildColorMap(keys) {
  const map = {};
  keys.forEach((key, i) => {
    map[key] = i < SERIES.length ? SERIES[i] : colorForKey(key, i);
  });
  return map;
}

const tooltip = (formatValue) => ({
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
  callbacks: {
    label: (ctx) => ` ${ctx.dataset.label}: ${formatValue(ctx.parsed.y)}`,
  },
});

/**
 * Base options for every time-series line/area chart in the app.
 *
 * @param formatY      value -> string, used for both y ticks and the tooltip
 * @param showLegend   legend is mandatory for >= 2 series, pointless for one
 * @param stacked      stacked area (portfolio composition)
 */
export function timeSeriesOptions({ formatY, showLegend = true, stacked = false } = {}) {
  const fmt = formatY || ((v) => v);
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 250 },
    // Crosshair-style read: hovering anywhere in the column reports every
    // series at that date, which is the question these charts are asked.
    interaction: { mode: 'index', intersect: false },
    elements: {
      line: { borderWidth: 2, tension: 0.06 },
      point: { radius: 0, hoverRadius: 5, hitRadius: 12 },
    },
    plugins: {
      legend: {
        display: showLegend,
        position: 'top',
        align: 'end',
        labels: {
          color: INK.secondary,
          padding: 14,
          font: { family: FONT_SANS, size: 11 },
          // Line charts get a stroke swatch, which reproduces the dash pattern --
          // so the dashed benchmark is identifiable in the legend by more than
          // its colour. Stacked areas get a filled box, matching the band.
          // (rectRounded + usePointStyle drew an empty outline for datasets with
          // a transparent background, which read as a rendering glitch.)
          ...(stacked
            ? { boxWidth: 12, boxHeight: 12 }
            : { usePointStyle: true, pointStyle: 'line', pointStyleWidth: 26, boxHeight: 2 }),
        },
      },
      tooltip: tooltip(fmt),
    },
    scales: {
      x: {
        stacked,
        grid: { display: false },
        border: { color: INK.grid },
        ticks: {
          color: INK.axis,
          maxTicksLimit: 8,
          maxRotation: 0,
          autoSkip: true,
          font: { family: FONT_MONO, size: 9 },
          padding: 6,
        },
      },
      y: {
        stacked,
        grid: { color: INK.grid, drawTicks: false },
        border: { display: false },
        ticks: {
          color: INK.axis,
          font: { family: FONT_MONO, size: 10 },
          padding: 8,
          maxTicksLimit: 6,
          callback: (v) => fmt(v),
        },
      },
    },
  };
}

// Horizontal bars (per-position weights, P&L contribution). No legend: the
// category axis already names every bar.
export function horizontalBarOptions({ formatValue } = {}) {
  const fmt = formatValue || ((v) => v);
  return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 250 },
    plugins: {
      legend: { display: false },
      tooltip: tooltip(fmt),
    },
    scales: {
      x: {
        grid: { color: INK.grid, drawTicks: false },
        border: { display: false },
        ticks: { color: INK.axis, font: { family: FONT_MONO, size: 9 }, callback: (v) => fmt(v) },
      },
      y: {
        grid: { display: false },
        border: { display: false },
        ticks: { color: INK.secondary, font: { family: FONT_SANS, size: 11 } },
      },
    },
  };
}

export function doughnutOptions({ formatValue } = {}) {
  const fmt = formatValue || ((v) => v);
  return {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '62%',
    // A 2px surface-coloured gap between arcs, so adjacent slices stay
    // separable without relying on a hue difference.
    borderColor: INK.surface,
    borderWidth: 2,
    animation: { duration: 250 },
    plugins: {
      legend: { display: false }, // rendered as an HTML list beside the chart
      tooltip: {
        ...tooltip(fmt),
        callbacks: {
          label: (ctx) => ` ${ctx.label}: ${fmt(ctx.parsed)}`,
        },
      },
    },
  };
}
