import React, { useMemo, useState, useEffect } from 'react';
import { Line } from 'react-chartjs-2';
import 'chart.js/auto';
import { AreaChart, TrendingUp, HelpCircle } from 'lucide-react';
import './ChartContainer.css';

const TIME_WINDOWS = ['1D', '1W', '1M', 'YTD', '1Y', '5Y', '10Y', 'All'];

export default function ChartContainer({
  rawData,
  selectedTickers,
  loading,
  tickerColors,
  onWindowChange
}) {
  const [selectedWindow, setSelectedWindow] = useState('1Y');
  const [customRangeTs, setCustomRangeTs] = useState([0, Date.now()]);

  // Each window implies its own /api/data resolution (see utils/resolution.js) -- the
  // slider's freeform 'Custom' range doesn't, since it's just visually slicing whatever
  // was already fetched for the last preset window.
  const handleSelectWindow = (win) => {
    setSelectedWindow(win);
    if (win !== 'Custom') onWindowChange?.(win);
  };

  // 1. Process all available timestamps from rawData
  const allTimestamps = useMemo(() => {
    if (!rawData || rawData.length === 0) return [];
    return Array.from(new Set(rawData.map((d) => d.timestamp)))
      .map(ts => new Date(ts).getTime())
      .sort((a, b) => a - b);
  }, [rawData]);

  // 2. Determine the active timestamp range in milliseconds
  const activeRangeTs = useMemo(() => {
    if (allTimestamps.length === 0) return [0, 0];
    const latest = allTimestamps[allTimestamps.length - 1];
    const latestDate = new Date(latest);

    if (selectedWindow === 'Custom') return customRangeTs;

    let start = allTimestamps[0];
    if (selectedWindow === '1D') start = new Date(latestDate).setDate(latestDate.getDate() - 1);
    else if (selectedWindow === '1W') start = new Date(latestDate).setDate(latestDate.getDate() - 7);
    else if (selectedWindow === '1M') start = new Date(latestDate).setMonth(latestDate.getMonth() - 1);
    else if (selectedWindow === 'YTD') start = new Date(latestDate.getFullYear(), 0, 1).getTime();
    else if (selectedWindow === '1Y') start = new Date(latestDate).setFullYear(latestDate.getFullYear() - 1);
    else if (selectedWindow === '5Y') start = new Date(latestDate).setFullYear(latestDate.getFullYear() - 5);
    else if (selectedWindow === '10Y') start = new Date(latestDate).setFullYear(latestDate.getFullYear() - 10);
    else if (selectedWindow === 'All') start = allTimestamps[0];

    // Ensure start doesn't precede the oldest available data if a specific window is selected
    if (start < allTimestamps[0] && selectedWindow !== '1D' && selectedWindow !== '1W') {
        start = allTimestamps[0];
    }
    
    return [start, latest];
  }, [selectedWindow, customRangeTs, allTimestamps]);

  // Update custom range to visually sync the slider when a window button is clicked
  useEffect(() => {
      if (selectedWindow !== 'Custom' && allTimestamps.length > 0) {
          setCustomRangeTs([...activeRangeTs]);
      }
  }, [selectedWindow, allTimestamps]);

  // 3. Filter timestamps to the active range and apply downsampling if > 500 points
  const visibleTimestamps = useMemo(() => {
    const [start, end] = activeRangeTs;
    const filtered = allTimestamps.filter(ts => ts >= start && ts <= end);
    
    if (filtered.length > 500) {
      const factor = Math.ceil(filtered.length / 500);
      return filtered.filter((_, index) => index % factor === 0 || index === filtered.length - 1);
    }
    return filtered;
  }, [allTimestamps, activeRangeTs]);

  // 4. Build chart data using only visible timestamps
  const chartData = useMemo(() => {
    if (visibleTimestamps.length === 0) return null;

    const labels = visibleTimestamps.map((ts) =>
      new Date(ts).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    );

    const datasets = selectedTickers.map((ticker) => {
      const color = tickerColors[ticker] || '#10b981';
      
      const dataPoints = visibleTimestamps.map((ts) => {
        // Find by timestamp strictly, using the original ISO string could be tricky, 
        // so we find by converting back to time or matching the closest.
        // For performance, doing it this way is okay for small arrays, but map helps:
        const record = rawData.find((d) => new Date(d.timestamp).getTime() === ts && d.ticker === ticker);
        return record ? record.close : null;
      });

      return {
        label: `${ticker} Close`,
        data: dataPoints,
        borderColor: color,
        borderWidth: 2,
        pointRadius: selectedTickers.length > 2 ? 0 : 1.5,
        pointHoverRadius: 6,
        pointBackgroundColor: color,
        pointBorderColor: '#070a13',
        pointBorderWidth: 1.5,
        backgroundColor: (context) => {
          const chart = context.chart;
          const { ctx, chartArea } = chart;
          if (!chartArea) return null;
          
          const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          gradient.addColorStop(0, `${color}25`);
          gradient.addColorStop(1, `${color}00`);
          return gradient;
        },
        fill: true,
        tension: 0.08,
        spanGaps: true
      };
    });

    return { labels, datasets };
  }, [rawData, selectedTickers, tickerColors, visibleTimestamps]);

  // Chart Options
  const chartOptions = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    plugins: {
      legend: {
        display: selectedTickers.length > 1,
        position: 'top',
        labels: {
          boxWidth: 10,
          boxHeight: 10,
          color: '#94a3b8',
          font: { family: 'Inter, system-ui', size: 11, weight: 500 },
          padding: 15
        }
      },
      tooltip: {
        backgroundColor: '#0e1424',
        titleColor: '#f8fafc',
        bodyColor: '#e2e8f0',
        borderColor: 'rgba(255, 255, 255, 0.08)',
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        titleFont: { family: 'JetBrains Mono, monospace', size: 11, weight: 600 },
        bodyFont: { family: 'Inter, system-ui', size: 12 },
        callbacks: {
          label: (context) => {
            const label = context.dataset.label.split(' ')[0] || '';
            const value = context.parsed.y;
            return ` ${label}: $${value !== null ? value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : 'N/A'}`;
          }
        }
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(255, 255, 255, 0.03)', drawTicks: false },
        ticks: { color: '#64748b', font: { family: 'JetBrains Mono, monospace', size: 9 }, maxTicksLimit: 10, padding: 8 }
      },
      y: {
        grid: { color: 'rgba(255, 255, 255, 0.03)', drawTicks: false },
        ticks: { color: '#64748b', font: { family: 'JetBrains Mono, monospace', size: 10 }, padding: 8, callback: (value) => `$${value}` }
      }
    }
  }), [selectedTickers]);

  // Mini preview path logic
  const miniPreviewPath = useMemo(() => {
    if (allTimestamps.length === 0 || selectedTickers.length === 0) return '';
    const ticker = selectedTickers[0];
    const maxTs = allTimestamps[allTimestamps.length - 1];
    const minTs = allTimestamps[0];
    const tsRange = maxTs - minTs || 1;
    
    // Build path using the first selected ticker
    const tickerData = rawData.filter(d => d.ticker === ticker).sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
    if (tickerData.length === 0) return '';
    
    const maxPrice = Math.max(...tickerData.map(d => d.close));
    const minPrice = Math.min(...tickerData.map(d => d.close));
    const priceRange = maxPrice - minPrice || 1;
  
    const points = tickerData.map(d => {
      const x = ((new Date(d.timestamp).getTime() - minTs) / tsRange) * 100;
      const y = 100 - (((d.close - minPrice) / priceRange) * 100);
      return `${x},${y}`;
    });
  
    return `M ${points.join(' L ')}`;
  }, [rawData, allTimestamps, selectedTickers]);

  // Slider indices and percentages
  const getClosestIndex = (ts) => {
    if (allTimestamps.length === 0) return 0;
    let low = 0, high = allTimestamps.length - 1;
    while (low < high) {
      const mid = Math.floor((low + high) / 2);
      if (allTimestamps[mid] < ts) low = mid + 1;
      else high = mid;
    }
    return low;
  };

  const startIndex = getClosestIndex(activeRangeTs[0]);
  const endIndex = getClosestIndex(activeRangeTs[1]);
  const maxIndex = Math.max(0, allTimestamps.length - 1);
  const startPercent = maxIndex > 0 ? (startIndex / maxIndex) * 100 : 0;
  const endPercent = maxIndex > 0 ? (endIndex / maxIndex) * 100 : 100;

  const handleSliderChange = (e, index) => {
    const val = Number(e.target.value);
    const newTs = allTimestamps[val];
    const newRange = [...activeRangeTs];
    newRange[index] = newTs;
    
    // Prevent crossing
    if (index === 0 && newRange[0] > newRange[1]) newRange[0] = newRange[1];
    if (index === 1 && newRange[1] < newRange[0]) newRange[1] = newRange[0];
 
    setCustomRangeTs(newRange);
    setSelectedWindow('Custom');
  };

  return (
    <main className="chart-panel panel glass">
      <div className="panel-header">
        <div className="panel-header-row">
          <h2 className="panel-title">
            <AreaChart size={18} className="title-icon-primary" />
            <span>Interactive Timeseries Terminal</span>
            {selectedTickers.length > 1 && (
                <div className="multi-badge badge badge-info ml-2">Overlay</div>
            )}
          </h2>
          
          <div className="time-window-controls">
            {TIME_WINDOWS.map(win => (
              <button 
                key={win}
                className={`time-btn ${selectedWindow === win ? 'active' : ''}`}
                onClick={() => handleSelectWindow(win)}
              >
                {win}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="chart-viewport">
        {loading ? (
          <div className="chart-overlay-state">
            <div className="chart-loading-indicator">
              <div className="loader-ring" />
              <p className="state-text">Streaming telemetry from QuestDB...</p>
            </div>
          </div>
        ) : null}

        {!loading && selectedTickers.length === 0 ? (
          <div className="chart-overlay-state">
            <TrendingUp size={36} className="state-icon-muted" />
            <p className="state-title">No Node Selected</p>
            <p className="state-subtitle">Activate one or more assets in the sidebar to trace curves.</p>
          </div>
        ) : null}

        {!loading && selectedTickers.length > 0 && (!rawData || rawData.length === 0) ? (
          <div className="chart-overlay-state">
            <HelpCircle size={36} className="state-icon-warn" />
            <p className="state-title">No Data In Range</p>
            <p className="state-subtitle">Backfilling in progress or API database is empty for selected assets.</p>
          </div>
        ) : null}

        {chartData && selectedTickers.length > 0 && rawData && rawData.length > 0 && (
          <div className="chart-wrapper">
            <Line data={chartData} options={chartOptions} />
          </div>
        )}

        {/* Sliding Window Slider below the chart */}
        {allTimestamps.length > 0 && selectedTickers.length > 0 && (
            <div className="slider-container">
              <svg className="mini-preview" viewBox="0 0 100 100" preserveAspectRatio="none">
                 {miniPreviewPath && <path d={miniPreviewPath} stroke="rgba(255,255,255,0.15)" fill="none" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
              </svg>
              
              <div className="slider-overlay" style={{ left: `${startPercent}%`, width: `${endPercent - startPercent}%` }} />
           
              <input 
                 type="range" 
                 min="0" 
                 max={maxIndex} 
                 value={startIndex} 
                 onChange={(e) => handleSliderChange(e, 0)}
                 className="range-input"
              />
              <input 
                 type="range" 
                 min="0" 
                 max={maxIndex} 
                 value={endIndex} 
                 onChange={(e) => handleSliderChange(e, 1)}
                 className="range-input"
              />
           </div>
        )}
      </div>
    </main>
  );
}
