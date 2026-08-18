import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { Activity, Briefcase, Compass } from 'lucide-react';
import Header from './components/Header.jsx';
import TickerSelector from './components/TickerSelector.jsx';
import TickerTracker from './components/TickerTracker.jsx';
import ChartContainer from './components/ChartContainer.jsx';
import StatsGrid from './components/StatsGrid.jsx';
import PortfolioManager from './components/PortfolioManager.jsx';
import FearAndGreed from './components/FearAndGreed.jsx';
import Home from './components/Home.jsx';
import { WINDOW_RESOLUTION } from './utils/resolution.js';

const API_BASE = `http://${window.location.hostname}:8000/api`;

const PRESET_COLORS = [
  '#10b981', // Emerald
  '#6366f1', // Indigo
  '#06b6d4', // Cyan
  '#f43f5e', // Rose
  '#eab308', // Amber
  '#a855f7', // Purple
  '#f97316', // Orange
  '#3b82f6'  // Blue
];

export default function App() {
  const location = useLocation();
  const [tickers, setTickers] = useState([]);
  const [selectedTickers, setSelectedTickers] = useState([]);
  const [resolution, setResolution] = useState('1d');
  const [rawData, setRawData] = useState([]);
  const [tickersLoading, setTickersLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(false);
  const [isApiConnected, setIsApiConnected] = useState(false);
  const cachedTickers = useRef(new Set());
  const cachedResolution = useRef('1d');

  // Dynamically assign colors to tickers from preset palette
  const tickerColors = useMemo(() => {
    const mapping = {};
    tickers.forEach((ticker, idx) => {
      mapping[ticker] = PRESET_COLORS[idx % PRESET_COLORS.length];
    });
    return mapping;
  }, [tickers]);

  // Fetch tracked registry of tickers
  const fetchTickers = useCallback(async (selectNewTicker = null) => {
    setTickersLoading(true);
    try {
      const response = await fetch(`${API_BASE}/tickers`);
      if (response.ok) {
        const data = await response.json();
        setTickers(data);
        setIsApiConnected(true);

        if (data.length > 0) {
          if (selectNewTicker && data.includes(selectNewTicker)) {
            setSelectedTickers((prev) => {
              if (prev.includes(selectNewTicker)) return prev;
              return [...prev, selectNewTicker];
            });
          } else if (selectedTickers.length === 0) {
            setSelectedTickers([data[0]]);
          }
        }
      } else {
        setIsApiConnected(false);
      }
    } catch (err) {
      console.error('Failed to connect to backend registry:', err);
      setIsApiConnected(false);
    } finally {
      setTickersLoading(false);
    }
  }, [selectedTickers]);

  // Fetch telemetry historical price data for the Terminal's selected tickers, at the
  // resolution implied by the selected time window (see handleWindowChange below).
  // Portfolio Manager fetches its own price history independently -- it needs a
  // resolution matching the portfolio's full lifetime span, not whatever window the
  // Terminal chart happens to have selected.
  const fetchTelemetryData = useCallback(async (forceRefresh = false) => {
    if (selectedTickers.length === 0) {
      setRawData([]);
      cachedTickers.current.clear();
      return;
    }

    const isForced = forceRefresh === true;
    let uncachedTickers = selectedTickers;

    if (!isForced && resolution === cachedResolution.current) {
      uncachedTickers = selectedTickers.filter(t => !cachedTickers.current.has(t));
      if (uncachedTickers.length === 0) return;
    } else {
      cachedTickers.current.clear();
      cachedResolution.current = resolution;
    }

    setDataLoading(true);
    const tickersParam = uncachedTickers.join(',');
    try {
      const response = await fetch(
        `${API_BASE}/data?tickers=${tickersParam}&resolution=${resolution}&limit=5000`
      );
      if (response.ok) {
        const payload = await response.json();
        setRawData(prev => (isForced || cachedTickers.current.size === 0) ? (payload.data || []) : [...prev, ...(payload.data || [])]);
        uncachedTickers.forEach(t => cachedTickers.current.add(t));
        setIsApiConnected(true);
      } else {
        console.error('Failed to retrieve telemetry data:', response.statusText);
      }
    } catch (err) {
      console.error('Network failure pulling telemetry data:', err);
    } finally {
      setDataLoading(false);
    }
  }, [selectedTickers, resolution]);

  // Each Terminal time-window implies its own resolution -- see utils/resolution.js.
  const handleWindowChange = useCallback((window) => {
    setResolution(WINDOW_RESOLUTION[window] || '1d');
  }, []);

  // Handle ticker list selections
  const handleToggleTicker = useCallback((ticker) => {
    setSelectedTickers((prev) => {
      if (prev.includes(ticker)) {
        return prev.filter((t) => t !== ticker);
      } else {
        return [...prev, ticker];
      }
    });
  }, []);

  const handleTrackSuccess = useCallback(async (newTicker) => {
    await fetchTickers(newTicker);
  }, [fetchTickers]);

  // --- LIFECYCLE ---
  useEffect(() => {
    fetchTickers();
  }, []);

  // Sync historical chart data when selected nodes or resolution changes
  useEffect(() => {
    fetchTelemetryData();
  }, [selectedTickers, resolution, fetchTelemetryData]);

  // Light background polling to update terminal data every 5 minutes
  useEffect(() => {
    const timer = setInterval(() => {
      fetchTelemetryData(true);
    }, 300000);

    return () => clearInterval(timer);
  }, [fetchTelemetryData]);

  return (
    <div className="app-container">
      {location.pathname !== '/' && (
        <Header
          onRefresh={fetchTelemetryData}
          loading={dataLoading}
          isApiConnected={isApiConnected}
        />
      )}

      {location.pathname !== '/' && (
        <nav className="tab-navigation">
          <NavLink
            to="/terminal"
            className={({ isActive }) => `tab-btn ${isActive ? 'active' : ''}`}
          >
            <Activity size={16} />
            <span>Live Terminal</span>
          </NavLink>
          <NavLink
            to="/portfolio"
            className={({ isActive }) => `tab-btn ${isActive ? 'active' : ''}`}
          >
            <Briefcase size={16} />
            <span>Portfolio Manager</span>
          </NavLink>
          <NavLink
            to="/sentiment"
            className={({ isActive }) => `tab-btn ${isActive ? 'active' : ''}`}
          >
            <Compass size={16} />
            <span>Fear & Greed Index</span>
          </NavLink>
        </nav>
      )}

      <Routes>
        <Route path="/" element={<Home />} />
        
        <Route path="/terminal" element={
          <div className="dashboard-grid animate-fade-in">
            <aside className="sidebar flex flex-col gap-6">
              <TickerSelector
                tickers={tickers}
                selectedTickers={selectedTickers}
                onToggleTicker={handleToggleTicker}
                loading={tickersLoading}
                tickerColors={tickerColors}
              />
              <TickerTracker
                onTrackSuccess={handleTrackSuccess}
                apiBase={API_BASE}
              />
            </aside>

            <section className="main-content flex flex-col gap-6">
              <ChartContainer
                rawData={rawData.filter(d => selectedTickers.includes(d.ticker))}
                selectedTickers={selectedTickers}
                loading={dataLoading}
                tickerColors={tickerColors}
                onWindowChange={handleWindowChange}
              />
              
              <StatsGrid
                rawData={rawData.filter(d => selectedTickers.includes(d.ticker))}
                selectedTickers={selectedTickers}
                tickerColors={tickerColors}
              />
            </section>
          </div>
        } />

        <Route path="/portfolio" element={
          <PortfolioManager
            trackedTickers={tickers}
            apiBase={API_BASE}
            onTrackNewTicker={handleTrackSuccess}
          />
        } />

        <Route path="/sentiment" element={
          <FearAndGreed apiBase={API_BASE} />
        } />
      </Routes>
    </div>
  );
}
