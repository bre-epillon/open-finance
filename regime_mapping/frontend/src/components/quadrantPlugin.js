import { FONT_SANS, INK, QUADRANT_EDGE, QUADRANT_TINT } from '../theme.js';

// Draws the four quadrant regions, their names, the zero crosshair and an
// arrowhead at the most recent point.
//
// This is the part that makes the scatter readable: the quadrant is the
// message, and it is carried by POSITION plus a text label. The tints are
// support, never the only cue -- so the plot still works in grayscale, in
// forced-colors mode, and for a reader with any form of colour blindness.
//
// Both plugins are exported for LOCAL registration -- passed to one chart via
// react-chartjs-2's `plugins` prop, never Chart.register(). Chart.register is
// global: registering these drew the quadrant tints and a stray "REFLATION"
// label across the sentiment history chart on the same page.

// [xSign, ySign, name] -- x is growth momentum, y is inflation momentum.
const REGIONS = [
  [1, -1, 'Goldilocks'],
  [1, 1, 'Reflation'],
  [-1, 1, 'Stagflation'],
  [-1, -1, 'Deflation'],
];

function zeroPixels(chart) {
  const { x, y } = chart.scales;
  return { zx: x.getPixelForValue(0), zy: y.getPixelForValue(0) };
}

export const quadrantBackground = {
  id: 'quadrantBackground',
  // beforeDatasetsDraw so the regions sit under the trajectory, not over it.
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    const { left, right, top, bottom } = chartArea;
    const { zx, zy } = zeroPixels(chart);

    ctx.save();
    REGIONS.forEach(([sx, sy, name]) => {
      const x0 = sx > 0 ? zx : left;
      const x1 = sx > 0 ? right : zx;
      const y0 = sy > 0 ? top : zy;
      const y1 = sy > 0 ? zy : bottom;
      if (x1 <= x0 || y1 <= y0) return;

      ctx.fillStyle = QUADRANT_TINT[name];
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0);

      // Name in the outer corner of its own region, away from the origin
      // where the trajectory spends most of its time.
      ctx.fillStyle = INK.muted;
      ctx.font = `600 11px ${FONT_SANS}`;
      ctx.textAlign = sx > 0 ? 'right' : 'left';
      ctx.textBaseline = sy > 0 ? 'top' : 'bottom';
      ctx.fillText(name.toUpperCase(),
        sx > 0 ? x1 - 10 : x0 + 10,
        sy > 0 ? y0 + 8 : y1 - 8);
    });

    // Zero crosshair. Slightly brighter than the grid, because these two
    // lines are the axes that matter -- everything is read relative to them.
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, zy); ctx.lineTo(right, zy);
    ctx.moveTo(zx, top); ctx.lineTo(zx, bottom);
    ctx.stroke();
    ctx.restore();
  },
};

export const nowMarker = {
  id: 'nowMarker',
  afterDatasetsDraw(chart, _args, opts) {
    const meta = chart.getDatasetMeta(0);
    const points = meta?.data;
    if (!points || points.length < 2) return;

    const last = points[points.length - 1];
    const prev = points[points.length - 2];
    const angle = Math.atan2(last.y - prev.y, last.x - prev.x);
    const color = QUADRANT_EDGE[opts?.quadrant] || INK.primary;

    const ctx = chart.ctx;
    ctx.save();
    // Arrowhead on the direction of travel, so "which way is the economy
    // heading" is answered without reading the tooltip.
    ctx.translate(last.x, last.y);
    ctx.rotate(angle);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(11, 0);
    ctx.lineTo(1, 5.5);
    ctx.lineTo(1, -5.5);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // 2px surface ring, so the latest point stays separable where the path
    // doubles back over itself.
    ctx.save();
    ctx.beginPath();
    ctx.arc(last.x, last.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = INK.surface;
    ctx.stroke();
    ctx.restore();
  },
};
