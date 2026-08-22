import React, { useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import {
  CategoryScale, Chart, Filler, LineElement, LinearScale, PointElement,
  Tooltip,
} from 'chart.js';
import { History } from 'lucide-react';
import {
  FONT_MONO, FONT_SANS, INK, TOOLTIP, sentimentColor,
} from '../theme.js';

Chart.register(CategoryScale, LinearScale, PointElement, LineElement, Filler,
  Tooltip);

// One series, so no legend -- the panel title names it. The band edges from
// core.sentiment.BANDS are drawn as reference lines instead, because "is this
// fear or greed" is read against those thresholds and not against the axis.
const BANDS = [25, 45, 55, 75];

const bandLines = {
  id: 'sentimentBands',
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.setLineDash([3, 4]);
    ctx.lineWidth = 1;
    BANDS.forEach((v) => {
      const y = scales.y.getPixelForValue(v);
      // 50 is the one that matters most, so it reads a step brighter.
      ctx.strokeStyle = v === 45 || v === 55
        ? 'rgba(255,255,255,0.13)' : 'rgba(255,255,255,0.07)';
      ctx.beginPath();
      ctx.moveTo(chartArea.left, y);
      ctx.lineTo(chartArea.right, y);
      ctx.stroke();
    });
    ctx.restore();
  },
};
// Local, not Chart.register: a globally registered plugin draws on every
// chart in the app, which is how the regime scatter's quadrant tints ended up
// on this panel.
const LOCAL_PLUGINS = [bandLines];

export default function SentimentHistory({ history }) {
  const points = history?.points || [];

  const { data, options } = useMemo(() => {
    const last = points.length ? points[points.length - 1].composite : 50;
    const accent = sentimentColor(last);
    return {
      data: {
        labels: points.map((p) => p.as_of),
        datasets: [{
          label: 'Composite',
          data: points.map((p) => p.composite),
          borderColor: accent,
          borderWidth: 2,
          fill: 'origin',
          backgroundColor: `${accent}1f`,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHitRadius: 12,
          tension: 0.15,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        // Crosshair read: hovering anywhere in the column reports that day.
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            ...TOOLTIP,
            callbacks: {
              label: (item) => {
                const p = points[item.dataIndex];
                return ` ${Math.round(p.composite)}/100 · ${p.components} of 5`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: INK.grid },
            ticks: {
              color: INK.axis, maxTicksLimit: 6, maxRotation: 0,
              autoSkip: true, font: { family: FONT_MONO, size: 9 },
              // Month precision, not the full date: at a narrow viewport six
              // full ISO dates run into each other, and the day of the month
              // is not what anyone reads off a 250-session axis.
              callback: (_v, i) => (points[i]?.as_of || '').slice(0, 7),
            },
          },
          y: {
            min: 0, max: 100,
            grid: { display: false },
            border: { display: false },
            ticks: {
              color: INK.axis, stepSize: 25,
              font: { family: FONT_MONO, size: 9 },
            },
          },
        },
      },
    };
  }, [points]);

  if (!points.length) {
    return <p className="state-text">No sentiment history yet.</p>;
  }

  return (
    <div className="sent-history">
      <div className="panel-head">
        <h2><History size={15} /> Greed &amp; Fear, last {points.length} sessions</h2>
        <div className="panel-meta"><span>0 = extreme fear · 100 = extreme greed</span></div>
      </div>
      <div className="chart-box short">
        <Line data={data} options={options} plugins={LOCAL_PLUGINS} />
      </div>
      <p className="caption">
        Dashed lines mark the band edges at 25, 45, 55 and 75. The fill takes
        the colour of the latest reading, so the panel says which side of
        neutral the market is on before any number is read.
      </p>
    </div>
  );
}
