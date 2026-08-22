import React, { useMemo, useState } from 'react';
import { Scatter } from 'react-chartjs-2';
import {
  Chart, LinearScale, PointElement, LineElement, Tooltip, Filler,
} from 'chart.js';
import { Table2, TrendingUp } from 'lucide-react';
import { nowMarker, quadrantBackground } from './quadrantPlugin.js';
import {
  FONT_MONO, FONT_SANS, INK, TOOLTIP, fmtSigned, recencyColor,
} from '../theme.js';

// Scales and elements are shared and safe to register globally. The two
// custom plugins are NOT -- they are passed to this chart only, via the
// `plugins` prop below.
Chart.register(LinearScale, PointElement, LineElement, Tooltip, Filler);

const LOCAL_PLUGINS = [quadrantBackground, nowMarker];

// Marker radius encodes acceleration (Gamma). Bigger point = the move is
// speeding up. That is what Gamma is for; a column in a table would waste it.
const MIN_RADIUS = 3;
const MAX_RADIUS = 9;

function radiusFor(point) {
  const accel = Math.hypot(point.growth_gamma || 0, point.inflation_gamma || 0);
  return Math.min(MAX_RADIUS, MIN_RADIUS + accel * 4);
}

export default function RegimeScatter({ history, quadrant }) {
  const [showTable, setShowTable] = useState(false);
  const points = history?.points || [];

  const { data, options } = useMemo(() => {
    const n = points.length;
    const xy = points.map((p) => ({ x: p.growth_delta, y: p.inflation_delta }));
    const extent = Math.max(
      0.6,
      ...xy.flatMap((p) => [Math.abs(p.x || 0), Math.abs(p.y || 0)]),
    ) * 1.15;

    return {
      data: {
        // One series: a path through time. No legend -- the panel title names
        // it, and a legend box for a single series is noise.
        datasets: [{
          label: 'Regime path',
          data: xy,
          showLine: true,
          borderColor: 'rgba(59, 130, 246, 0.35)',
          borderWidth: 2,
          tension: 0.15,
          pointRadius: points.map(radiusFor),
          pointHoverRadius: points.map((p) => radiusFor(p) + 3),
          pointHitRadius: 14,
          pointBackgroundColor: points.map((_, i) => recencyColor(i, n)),
          pointBorderColor: INK.surface,
          pointBorderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        // Per-point, not per-index: on a scatter the reader is asking about
        // one month, not a column.
        interaction: { mode: 'nearest', intersect: true },
        plugins: {
          legend: { display: false },
          nowMarker: { quadrant },
          tooltip: {
            ...TOOLTIP,
            callbacks: {
              title: (items) => points[items[0].dataIndex]?.as_of || '',
              label: (item) => {
                const p = points[item.dataIndex];
                if (!p) return '';
                return [
                  `${p.quadrant}  (confidence ${(p.confidence ?? 0).toFixed(2)})`,
                  `Growth    Δ ${fmtSigned(p.growth_delta)}   Γ ${fmtSigned(p.growth_gamma)}`,
                  `Inflation Δ ${fmtSigned(p.inflation_delta)}   Γ ${fmtSigned(p.inflation_gamma)}`,
                  `Levels    growth ${fmtSigned(p.growth_z)}  inflation ${fmtSigned(p.inflation_z)}`,
                ];
              },
            },
          },
        },
        scales: {
          x: {
            min: -extent, max: extent,
            title: { display: true, text: 'Growth momentum  (Δ, sd per quarter)',
                     color: INK.secondary,
                     font: { family: FONT_SANS, size: 11 } },
            grid: { color: INK.grid, drawTicks: false },
            border: { display: false },
            ticks: { color: INK.axis, maxTicksLimit: 7,
                     font: { family: FONT_MONO, size: 9 } },
          },
          y: {
            min: -extent, max: extent,
            title: { display: true, text: 'Inflation momentum  (Δ, sd per quarter)',
                     color: INK.secondary,
                     font: { family: FONT_SANS, size: 11 } },
            grid: { color: INK.grid, drawTicks: false },
            border: { display: false },
            ticks: { color: INK.axis, maxTicksLimit: 7,
                     font: { family: FONT_MONO, size: 9 } },
          },
        },
      },
    };
  }, [points, quadrant]);

  if (!points.length) {
    return <p className="state-text">No regime history yet.</p>;
  }

  return (
    <div className="scatter">
      <div className="panel-head">
        <h2><TrendingUp size={15} /> Regime trajectory</h2>
        <div className="panel-meta">
          <span>{points.length} months to {points[points.length - 1].as_of}</span>
          <button type="button" className="ghost-button"
                  onClick={() => setShowTable((v) => !v)}
                  aria-pressed={showTable}>
            <Table2 size={13} /> {showTable ? 'Chart' : 'Table'}
          </button>
        </div>
      </div>

      {showTable ? (
        <TrajectoryTable points={points} />
      ) : (
        <>
          <div className="chart-box">
            <Scatter data={data} options={options} plugins={LOCAL_PLUGINS} />
          </div>
          <p className="caption">
            Path runs oldest (dark) to newest (light); the arrow points the way
            the economy is travelling. Marker size is acceleration (Γ) — a big
            marker means the move is speeding up.
          </p>
        </>
      )}
    </div>
  );
}

function TrajectoryTable({ points }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr><th>Month</th><th>Regime</th><th>Conf.</th>
              <th>Growth Δ</th><th>Infl. Δ</th>
              <th>Growth Γ</th><th>Infl. Γ</th></tr>
        </thead>
        <tbody>
          {[...points].reverse().map((p) => (
            <tr key={p.as_of}>
              <td>{p.as_of}</td>
              <td>{p.quadrant}</td>
              <td>{(p.confidence ?? 0).toFixed(2)}</td>
              <td>{fmtSigned(p.growth_delta)}</td>
              <td>{fmtSigned(p.inflation_delta)}</td>
              <td>{fmtSigned(p.growth_gamma)}</td>
              <td>{fmtSigned(p.inflation_gamma)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
