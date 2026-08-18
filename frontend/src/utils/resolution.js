// Maps a chart's time window to the /api/data resolution that keeps its point count
// reasonable: the server aggregates real OHLC bars at that size (QuestDB SAMPLE BY),
// rather than the client fetching everything and thinning it out after the fact.

// Terminal chart windows are fixed lookback periods, known upfront -- no need to derive
// their span from already-fetched data.
export const WINDOW_RESOLUTION = {
  '1D': '1d',
  '1W': '1d',
  '1M': '1d',
  YTD: '1d',
  '1Y': '1d',
  '5Y': '1w',
  '10Y': '1M',
  All: '1M',
};

// Portfolio charts don't have a window selector -- their span is however long the
// portfolio has existed, computed from the earliest transaction date.
export function resolutionForDays(days) {
  if (days <= 370) return '1d';
  if (days <= 1850) return '1w';
  return '1M';
}
