import { useCallback, useEffect, useState } from 'react';

// One hook, used by both panels -- which is the second use, so it earns being
// a hook at all (Architecture.md). /health rides along because the demo flag
// it carries has to be visible before anyone reads a number off the page.
// /health sits at the root, not under /api -- it reports on the service
// rather than the data, and conflating the two prefixes is how it ended up
// being fetched as /api/health and 404ing.
const API_ROOT = `http://${window.location.hostname}:8100`;
const API_BASE = `${API_ROOT}/api`;
const POLL_INTERVAL_MS = 5 * 60 * 1000;

async function getJson(path, base = API_BASE) {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) {
    // The API answers 503 with a specific, actionable message when the tables
    // are empty ("run backfill_history.py"). Surfacing it beats "failed to
    // fetch", which sends you looking at the network layer instead.
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body; the status text is all we have */
    }
    throw new Error(detail);
  }
  return response.json();
}

export function useEngine() {
  const [health, setHealth] = useState(null);
  const [regime, setRegime] = useState(null);
  const [history, setHistory] = useState(null);
  const [tilts, setTilts] = useState(null);
  const [sentiment, setSentiment] = useState(null);
  const [sentimentHistory, setSentimentHistory] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      // Settled rather than all: a missing sentiment table should not blank
      // the regime panel, and vice versa.
      const [hl, r, h, t, s, sh] = await Promise.allSettled([
        getJson('/health', API_ROOT),
        getJson('/regime'),
        getJson('/regime/history?months=36'),
        getJson('/regime/tilts'),
        getJson('/sentiment'),
        getJson('/sentiment/history?days=250'),
      ]);
      setHealth(hl.status === 'fulfilled' ? hl.value : null);
      setRegime(r.status === 'fulfilled' ? r.value : null);
      setHistory(h.status === 'fulfilled' ? h.value : null);
      setTilts(t.status === 'fulfilled' ? t.value : null);
      setSentiment(s.status === 'fulfilled' ? s.value : null);
      setSentimentHistory(sh.status === 'fulfilled' ? sh.value : null);

      const calls = [r, h, t, s, sh];
      const failures = calls.filter((p) => p.status === 'rejected');
      setError(failures.length === calls.length ? failures[0].reason.message : '');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load]);

  return { health, regime, history, tilts, sentiment, sentimentHistory,
           error, loading, reload: load };
}
