import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { Activity, Briefcase } from 'lucide-react';
import Header from './components/Header.jsx';
import ResearchView from './components/ResearchView.jsx';
import PortfolioManager from './components/PortfolioManager.jsx';
import Home from './components/Home.jsx';
import { WINDOW_RESOLUTION } from './utils/resolution.js';
import { buildColorMap } from './utils/chartTheme.js';

const API_BASE = `http://${window.location.hostname}:8000/api`;
const POLL_INTERVAL_MS = 5 * 60 * 1000;

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

  const tickerColors = useMemo(() => buildColorMap(tickers), [tickers]);

  // No dependency on selectedTickers: reading it here made this callback -- and
  // therefore every effect that depends on it -- rebuild on every click in the
  // sidebar, which tore down and restarted the background poller each time.
  // The "select the first ticker if nothing is selected" rule is expressed as a
  // functional update instead, which needs no read.
  const fetchTickers = useCallback(async (selectNewTicker = null) => {
    setTickersLoading(true);
    try {
      const response = await fetch(`${API_BASE}/tickers`);
      if (!response.ok) {
        setIsApiConnected(false);
        return;
      }
      const data = await response.json();
      setTickers(data);
      setIsApiConnected(true);
      if (data.length === 0) return;

      setSelectedTickers((prev) => {
        if (selectNewTicker && data.includes(selectNewTicker)) {
          return prev.includes(selectNewTicker) ? prev : [...prev, selectNewTicker];
        }
        return prev.length === 0 ? [data[0]] : prev;
      });
    } catch (err) {
      console.error('Failed to connect to backend registry:', err);
      setIsApiConnected(false);
    } finally {
      setTickersLoading(false);
    }
  }, []);

  // Terminal price history, at the resolution implied by the selected window.
  // Portfolio Manager fetches its own history independently -- it needs a
  // resolution matching the portfolio's full lifetime span, not whatever window
  // the Terminal chart happens to have open.
  const fetchTelemetryData = useCallback(async (forceRefresh = false) => {
    if (selectedTickers.length === 0) {
      setRawData([]);
      cachedTickers.current.clear();
      return;
    }

    const isForced = forceRefresh === true;
    let uncachedTickers = selectedTickers;

    if (!isForced && resolution === cachedResolution.current) {
      uncachedTickers = selectedTickers.filter((t) => !cachedTickers.current.has(t));
      if (uncachedTickers.length === 0) return;
    } else {
      cachedTickers.current.clear();
      cachedResolution.current = resolution;
    }

    setDataLoading(true);
    try {
      const response = await fetch(
        `${API_BASE}/data?tickers=${uncachedTickers.join(',')}&resolution=${resolution}&limit=5000`
      );
      if (!response.ok) {
        console.error('Failed to retrieve price data:', response.statusText);
        return;
      }
      const payload = await response.json();
      const isFullReplace = isForced || cachedTickers.current.size === 0;
      setRawData((prev) => (isFullReplace ? payload.data || [] : [...prev, ...(payload.data || [])]));
      uncachedTickers.forEach((t) => cachedTickers.current.add(t));
      setIsApiConnected(true);
    } catch (err) {
      console.error('Network failure pulling price data:', err);
    } finally {
      setDataLoading(false);
    }
  }, [selectedTickers, resolution]);

  // Keeps the poller below on a stable identity: it should fire every five
  // minutes regardless of how often the selection changes, rather than
  // restarting its timer each time.
  const latestFetch = useRef(fetchTelemetryData);
  useEffect(() => { latestFetch.current = fetchTelemetryData; }, [fetchTelemetryData]);

  const handleWindowChange = useCallback((window) => {
    setResolution(WINDOW_RESOLUTION[window] || '1d');
  }, []);

  const handleToggleTicker = useCallback((ticker) => {
    setSelectedTickers((prev) =>
      prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker]
    );
  }, []);

  const handleTrackSuccess = useCallback(
    async (newTicker) => { await fetchTickers(newTicker); },
    [fetchTickers]
  );

  const handleRefresh = useCallback(() => { fetchTelemetryData(true); }, [fetchTelemetryData]);

  useEffect(() => { fetchTickers(); }, [fetchTickers]);

  useEffect(() => { fetchTelemetryData(); }, [fetchTelemetryData]);

  useEffect(() => {
    const timer = setInterval(() => latestFetch.current(true), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  const visibleData = useMemo(
    () => rawData.filter((d) => selectedTickers.includes(d.ticker)),
    [rawData, selectedTickers]
  );

  const isLandingPage = location.pathname === '/';

  return (
    <div className="app-container">
      {!isLandingPage && (
        <>
          <Header onRefresh={handleRefresh} loading={dataLoading} isApiConnected={isApiConnected} />
          <nav className="tab-navigation">
            <NavLink to="/portfolio" className={({ isActive }) => `tab-btn ${isActive ? 'active' : ''}`}>
              <Briefcase size={16} />
              <span>Portfolio</span>
            </NavLink>
            <NavLink to="/terminal" className={({ isActive }) => `tab-btn ${isActive ? 'active' : ''}`}>
              <Activity size={16} />
              <span>Research</span>
            </NavLink>
          </nav>
        </>
      )}

      <Routes>
        <Route path="/" element={<Home />} />

        <Route
          path="/terminal"
          element={
            <ResearchView
              tickers={tickers}
              selectedTickers={selectedTickers}
              tickerColors={tickerColors}
              rawData={visibleData}
              tickersLoading={tickersLoading}
              dataLoading={dataLoading}
              apiBase={API_BASE}
              onToggleTicker={handleToggleTicker}
              onTrackSuccess={handleTrackSuccess}
              onWindowChange={handleWindowChange}
            />
          }
        />

        <Route
          path="/portfolio"
          element={
            <PortfolioManager
              trackedTickers={tickers}
              apiBase={API_BASE}
              onTrackNewTicker={handleTrackSuccess}
            />
          }
        />
      </Routes>
    </div>
  );
}
