import React, { useState, useEffect } from 'react';
import { Line, Doughnut } from 'react-chartjs-2';
import 'chart.js/auto';
import { AlertTriangle, TrendingUp, ShieldAlert, BarChart2, Activity } from 'lucide-react';
import './FearAndGreed.css';

export default function FearAndGreed({ apiBase }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isMounted = true;
    const fetchSentiment = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${apiBase}/v1/sentiment/fear-and-greed`);
        if (!response.ok) throw new Error('Failed to fetch sentiment data');
        const payload = await response.json();
        if (isMounted) setData(payload);
      } catch (err) {
        console.error(err);
        if (isMounted) setError('Unable to load Fear & Greed Index.');
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchSentiment();
    return () => { isMounted = false; };
  }, [apiBase]);

  if (loading) {
    return (
      <div className="sentiment-container panel glass flex-center">
        <div className="loader-ring"></div>
        <p className="state-text mt-4">Calculating quantitative sentiment...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="sentiment-container panel glass flex-center">
        <AlertTriangle size={36} className="state-icon-warn" />
        <p className="state-title">Error</p>
        <p className="state-subtitle">{error}</p>
      </div>
    );
  }

  // Dial configuration
  const score = Math.round(data.current_score);
  const gaugeData = {
    labels: ['Extreme Fear', 'Fear', 'Neutral', 'Greed', 'Extreme Greed'],
    datasets: [{
      data: [25, 25, 5, 20, 25],
      backgroundColor: ['#7f1d1d', '#f97316', '#64748b', '#22c55e', '#166534'],
      borderWidth: 0,
      circumference: 180,
      rotation: 270,
    }]
  };

  const getDialColor = (val) => {
    if (val < 25) return '#7f1d1d';
    if (val < 50) return '#f97316';
    if (val <= 54) return '#64748b';
    if (val < 75) return '#22c55e';
    return '#166534';
  };

  const needlePlugin = {
    id: 'needle',
    afterDraw: (chart) => {
      const { ctx, chartArea } = chart;
      if (!chartArea) return;
      const dataTotal = 100;
      const angle = Math.PI + (1 / dataTotal * score * Math.PI);
      const cx = chartArea.left + chartArea.width / 2;
      const cy = chartArea.bottom;

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(angle);
      ctx.beginPath();
      ctx.moveTo(0, -5);
      ctx.lineTo(chartArea.height * 0.8, 0);
      ctx.lineTo(0, 5);
      ctx.fillStyle = '#f8fafc';
      ctx.fill();
      ctx.restore();

      ctx.beginPath();
      ctx.arc(cx, cy, 8, 0, 10);
      ctx.fillStyle = '#f8fafc';
      ctx.fill();
      ctx.restore();
    }
  };

  const gaugeOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { enabled: false }
    },
    cutout: '80%'
  };

  // Historical Line Chart
  const histData = {
    labels: data.historical_series.map(item => item.date.substring(5)),
    datasets: [{
      label: 'Fear & Greed Score',
      data: data.historical_series.map(item => item.score),
      borderColor: '#3b82f6',
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      backgroundColor: 'rgba(59, 130, 246, 0.1)',
      tension: 0.3
    }]
  };
  
  const histOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' } },
      x: { grid: { display: false }, ticks: { display: false } }
    }
  };

  const getSubChartData = (key, color) => ({
    labels: data.historical_series.map(item => item.date.substring(5)),
    datasets: [{
      data: data.historical_series.map(item => item[key]),
      borderColor: color,
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      backgroundColor: `${color}20`,
      tension: 0.3
    }]
  });

  return (
    <div className="sentiment-container animate-fade-in">
      <div className="sentiment-header glass panel">
        <div className="gauge-wrapper">
          <Doughnut data={gaugeData} options={gaugeOptions} plugins={[needlePlugin]} />
          <div className="gauge-score-display" style={{ color: getDialColor(score) }}>
            <span className="gauge-val">{score}</span>
            <span className="gauge-label">{data.sentiment_label}</span>
          </div>
        </div>
        
        <div className="hist-wrapper">
          <h3 className="font-mono text-sm text-muted mb-2">Long-Term Trend</h3>
          <div className="hist-chart-container">
            <Line data={histData} options={histOptions} />
          </div>
        </div>
      </div>

      <h3 className="font-mono text-md mt-6 mb-4">Quantitative Sub-Components</h3>
      <div className="sub-grid">
        <div className="sub-card glass panel">
          <div className="sub-card-header">
            <div className="sub-card-title-group">
              <TrendingUp size={24} className="sub-icon text-blue-500" />
              <h4 className="sub-name">Market Momentum</h4>
            </div>
            <span className="sub-val font-mono">{Math.round(data.sub_components.momentum)}/100</span>
          </div>
          <p className="sub-desc">S&P 500 versus its 125-day moving average.</p>
          <div className="sub-chart-container">
            <Line data={getSubChartData('momentum', '#3b82f6')} options={histOptions} />
          </div>
        </div>
        
        <div className="sub-card glass panel">
          <div className="sub-card-header">
            <div className="sub-card-title-group">
              <Activity size={24} className="sub-icon text-rose-500" />
              <h4 className="sub-name">Market Volatility</h4>
            </div>
            <span className="sub-val font-mono">{Math.round(data.sub_components.volatility)}/100</span>
          </div>
          <p className="sub-desc">VIX index compared to its 50-day average. (Inverted: Lower volatility = Greed)</p>
          <div className="sub-chart-container">
            <Line data={getSubChartData('volatility', '#f43f5e')} options={histOptions} />
          </div>
        </div>
        
        <div className="sub-card glass panel">
          <div className="sub-card-header">
            <div className="sub-card-title-group">
              <ShieldAlert size={24} className="sub-icon text-amber-500" />
              <h4 className="sub-name">Safe Haven Demand</h4>
            </div>
            <span className="sub-val font-mono">{Math.round(data.sub_components.safe_haven)}/100</span>
          </div>
          <p className="sub-desc">Difference in 20-day returns of Stocks vs Treasury Bonds.</p>
          <div className="sub-chart-container">
            <Line data={getSubChartData('safe_haven', '#f59e0b')} options={histOptions} />
          </div>
        </div>
        
        <div className="sub-card glass panel">
          <div className="sub-card-header">
            <div className="sub-card-title-group">
              <AlertTriangle size={24} className="sub-icon text-orange-500" />
              <h4 className="sub-name">Junk Bond Demand</h4>
            </div>
            <span className="sub-val font-mono">{Math.round(data.sub_components.junk_bond)}/100</span>
          </div>
          <p className="sub-desc">Yield spread between junk bonds and safe corporate bonds.</p>
          <div className="sub-chart-container">
            <Line data={getSubChartData('junk_bond', '#f97316')} options={histOptions} />
          </div>
        </div>
        
        <div className="sub-card glass panel">
          <div className="sub-card-header">
            <div className="sub-card-title-group">
              <BarChart2 size={24} className="sub-icon text-indigo-500" />
              <h4 className="sub-name">Put/Call Options</h4>
            </div>
            <span className="sub-val font-mono">{Math.round(data.sub_components.put_call)}/100</span>
          </div>
          <p className="sub-desc">Proxy indicating options market downside protection volume.</p>
          <div className="sub-chart-container">
            <Line data={getSubChartData('put_call', '#6366f1')} options={histOptions} />
          </div>
        </div>
      </div>
    </div>
  );
}