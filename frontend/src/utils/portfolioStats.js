// Risk / concentration statistics derived from series already built elsewhere.
// Pure functions, no React, no fetching -- same contract as portfolioTimeSeries.js.

// Drawdown and volatility must be measured on the *time-weighted return index*,
// not on total portfolio value. A deposit raises value without being a gain, so
// a value-based drawdown curve would show a "recovery" every payday and would
// never show a drawdown at all during a period of steady contributions.

const TRADING_DAYS = 252;

// Used only for the Sharpe numerator. Deliberately a named constant rather than
// a live rate: the point is a stable, comparable ratio, and an ECB deposit-rate
// feed is not ingested. Update it when the regime moves materially.
export const RISK_FREE_RATE = 0.02;

/**
 * Underwater curve: percent below the running peak, at every point.
 * @param series output of buildPerformanceSeries (needs .date, .portfolioIndex)
 */
export function buildDrawdownSeries(series) {
  let peak = -Infinity;
  return series.map((p) => {
    if (p.portfolioIndex > peak) peak = p.portfolioIndex;
    const drawdown = peak > 0 ? (p.portfolioIndex / peak - 1) * 100 : 0;
    return { date: p.date, drawdown, peakIndex: peak };
  });
}

function stdDev(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

// Last index value of each calendar month, chained into month-over-month returns.
function monthlyReturns(series) {
  const lastByMonth = new Map();
  series.forEach((p) => lastByMonth.set(p.date.slice(0, 7), p.portfolioIndex));
  const months = [...lastByMonth.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const out = [];
  for (let i = 1; i < months.length; i++) {
    const prev = months[i - 1][1];
    if (prev > 0) out.push({ month: months[i][0], ret: (months[i][1] / prev - 1) * 100 });
  }
  return out;
}

/**
 * @param series output of buildPerformanceSeries
 * @returns null when there is not enough history to say anything honest
 */
export function computeRiskStats(series) {
  if (!series || series.length < 3) return null;

  const first = series[0];
  const last = series[series.length - 1];
  const spanDays = Math.max(
    1,
    Math.round((new Date(last.date) - new Date(first.date)) / 86400000)
  );

  const totalReturn = (last.portfolioIndex / 100 - 1) * 100;

  // Annualised only once there is a meaningful base. Annualising three weeks of
  // history produces a triple-digit number that means nothing, so it is
  // reported as null and the UI shows the raw total instead.
  const annualisedReturn =
    spanDays >= 180 ? ((last.portfolioIndex / 100) ** (365 / spanDays) - 1) * 100 : null;

  // Log returns between consecutive points. The series is on trading/event days,
  // so this is close enough to daily for a volatility estimate.
  const logReturns = [];
  for (let i = 1; i < series.length; i++) {
    const a = series[i - 1].portfolioIndex;
    const b = series[i].portfolioIndex;
    if (a > 0 && b > 0) logReturns.push(Math.log(b / a));
  }
  const dailyVol = stdDev(logReturns);
  const annualisedVol = dailyVol * Math.sqrt(TRADING_DAYS) * 100;

  const sharpe =
    annualisedReturn != null && annualisedVol > 0
      ? (annualisedReturn / 100 - RISK_FREE_RATE) / (annualisedVol / 100)
      : null;

  // Max drawdown, plus the dates that bracket it -- "how bad" is only actionable
  // alongside "when, and how long did it take to come back".
  let peak = -Infinity;
  let peakDate = first.date;
  let maxDrawdown = 0;
  let troughDate = null;
  let maxDrawdownPeakDate = null;
  series.forEach((p) => {
    if (p.portfolioIndex > peak) {
      peak = p.portfolioIndex;
      peakDate = p.date;
    }
    const dd = peak > 0 ? (p.portfolioIndex / peak - 1) * 100 : 0;
    if (dd < maxDrawdown) {
      maxDrawdown = dd;
      troughDate = p.date;
      maxDrawdownPeakDate = peakDate;
    }
  });
  const currentDrawdown = peak > 0 ? (last.portfolioIndex / peak - 1) * 100 : 0;

  const months = monthlyReturns(series);
  const best = months.reduce((m, c) => (m == null || c.ret > m.ret ? c : m), null);
  const worst = months.reduce((m, c) => (m == null || c.ret < m.ret ? c : m), null);
  const positiveMonths = months.filter((m) => m.ret > 0).length;

  return {
    spanDays,
    totalReturn,
    annualisedReturn,
    annualisedVol,
    sharpe,
    maxDrawdown,
    maxDrawdownPeakDate,
    maxDrawdownTroughDate: troughDate,
    currentDrawdown,
    bestMonth: best,
    worstMonth: worst,
    positiveMonthRate: months.length > 0 ? (positiveMonths / months.length) * 100 : null,
    monthCount: months.length,
  };
}

/**
 * Current allocation, by asset class and by individual position.
 *
 * @param activeHoldings usePortfolio's activeHoldings (needs ticker, name, currentValue)
 * @param bondsValue     bond cost basis (bonds have no live price feed)
 * @param cash           free cash
 */
export function computeAllocation(activeHoldings, bondsValue, cash) {
  const stocksValue = activeHoldings.reduce((sum, h) => sum + h.currentValue, 0);
  const bonds = Math.max(bondsValue, 0);

  // Total is raw net worth -- including a negative cash balance -- so this panel
  // always ties to the Net worth summary card. A negative balance cannot be drawn
  // as a share of the bar, so it is reported separately via `negativeCash`
  // instead of being silently clamped to zero (which made the two figures
  // disagree).
  const total = stocksValue + bonds + cash;
  if (total <= 0) return null;

  // Denominator for every weight below. Normally net worth. When the cash
  // balance is negative, net worth is smaller than what is actually invested, so
  // shares of it exceed 100% and overflow the bar -- in that case weights are
  // expressed against invested assets instead, and `basisLabel` tells the UI to
  // say so. One denominator at a time, always named.
  const investedAssets = stocksValue + bonds;
  const usesNetWorth = cash >= 0;
  const basis = usesNetWorth ? total : investedAssets;
  const basisLabel = usesNetWorth ? 'net worth' : 'invested assets';

  const byClass = [
    { key: 'stocks', label: 'Stocks & Funds', value: stocksValue },
    { key: 'bonds', label: 'Bonds', value: bonds },
    { key: 'cash', label: 'Cash', value: Math.max(cash, 0) },
  ]
    .filter((c) => c.value > 0)
    .map((c) => ({ ...c, weight: (c.value / basis) * 100 }));

  const positions = activeHoldings
    .map((h) => ({
      key: h.ticker,
      label: h.ticker,
      name: h.name,
      value: h.currentValue,
      weight: (h.currentValue / basis) * 100,
      weightOfEquity: stocksValue > 0 ? (h.currentValue / stocksValue) * 100 : 0,
    }))
    .sort((a, b) => b.value - a.value);

  // Herfindahl-Hirschman index on equity weights, reported as its "effective
  // number of positions" reciprocal -- far more legible than the raw index.
  // 10 equally-weighted names -> 10.0; one name at 90% -> ~1.2.
  const hhi = positions.reduce((sum, p) => sum + (p.weightOfEquity / 100) ** 2, 0);
  const effectivePositions = hhi > 0 ? 1 / hhi : 0;

  const top5Weight = positions.slice(0, 5).reduce((s, p) => s + p.weight, 0);

  return {
    total,
    basis,
    basisLabel,
    investedAssets,
    stocksValue,
    bondsValue: bonds,
    cash,
    negativeCash: cash < 0 ? cash : null,
    byClass,
    positions,
    effectivePositions,
    top5Weight,
    largest: positions[0] || null,
  };
}

// Groups anything with a { date, amount } shape into calendar months. Used by
// the income view; kept here so the month-bucketing rule lives in one place.
export function groupByMonth(items, amountOf = (i) => i.amount) {
  const map = new Map();
  items.forEach((i) => {
    const month = i.date.slice(0, 7);
    map.set(month, (map.get(month) || 0) + amountOf(i));
  });
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([month, amount]) => ({ month, amount }));
}
