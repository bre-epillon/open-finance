// Spec for the risk / allocation statistics.
//
// These read the performance index rather than total value, and that choice is
// the thing most worth guarding: a deposit raises value without being a gain,
// so a value-based drawdown curve "recovers" on every payday and never shows a
// real drawdown during a stretch of steady contributions.

import { describe, it, expect } from 'vitest';
import {
  buildDrawdownSeries,
  computeRiskStats,
  computeAllocation,
  groupByMonth,
  RISK_FREE_RATE,
} from './portfolioStats.js';

// An index series shaped like buildPerformanceSeries' output.
const idx = (values, startDate = '2025-01-01') => values.map((portfolioIndex, i) => {
  const d = new Date(Date.UTC(2025, 0, 1));
  d.setUTCDate(d.getUTCDate() + i);
  return { date: d.toISOString().slice(0, 10), portfolioIndex };
});

const monthly = (pairs) => pairs.map(([date, portfolioIndex]) => ({ date, portfolioIndex }));

const holding = (ticker, currentValue) => ({ ticker, name: `${ticker} Inc.`, currentValue });

// ===========================================================================
describe('buildDrawdownSeries', () => {
  it('reads zero while the index is making new highs', () => {
    const out = buildDrawdownSeries(idx([100, 110, 120]));
    out.forEach((p) => expect(p.drawdown).toBeCloseTo(0));
  });

  it('measures the fall from the running peak, not from the start', () => {
    // Peak 120, then 90: 90/120 - 1 = -25%.
    const out = buildDrawdownSeries(idx([100, 120, 90]));
    expect(out[2].drawdown).toBeCloseTo(-25);
  });

  it('returns to zero once the previous peak is regained', () => {
    const out = buildDrawdownSeries(idx([100, 120, 90, 120]));
    expect(out[3].drawdown).toBeCloseTo(0);
  });

  it('does not let a later peak rewrite an earlier drawdown', () => {
    const out = buildDrawdownSeries(idx([100, 120, 90, 200]));
    expect(out[2].drawdown).toBeCloseTo(-25);   // still measured against 120
    expect(out[3].drawdown).toBeCloseTo(0);
  });
});

// ===========================================================================
describe('computeRiskStats', () => {
  it('refuses to report anything from fewer than three points', () => {
    expect(computeRiskStats([])).toBeNull();
    expect(computeRiskStats(idx([100, 110]))).toBeNull();
  });

  it('reports max drawdown with the dates that bracket it', () => {
    const s = monthly([
      ['2025-01-31', 100], ['2025-02-28', 120],
      ['2025-03-31', 90],  ['2025-04-30', 130],
    ]);
    const out = computeRiskStats(s);
    expect(out.maxDrawdown).toBeCloseTo(-25);
    expect(out.maxDrawdownPeakDate).toBe('2025-02-28');
    expect(out.maxDrawdownTroughDate).toBe('2025-03-31');
  });

  it('reports the current drawdown separately from the worst one', () => {
    const out = computeRiskStats(monthly([
      ['2025-01-31', 100], ['2025-02-28', 200], ['2025-03-31', 100], ['2025-04-30', 180],
    ]));
    expect(out.maxDrawdown).toBeCloseTo(-50);
    expect(out.currentDrawdown).toBeCloseTo(-10);   // 180 against the 200 peak
  });

  it('computes total return from the first and last index value', () => {
    const out = computeRiskStats(idx([100, 105, 130]));
    expect(out.totalReturn).toBeCloseTo(30);
  });

  // Annualising three weeks of history produces a triple-digit number that
  // means nothing, so it is reported as null and the UI shows the raw total.
  it('declines to annualise a span shorter than 180 days', () => {
    const out = computeRiskStats(idx([100, 110, 120]));   // three days
    expect(out.annualisedReturn).toBeNull();
    expect(out.sharpe).toBeNull();
    expect(out.spanDays).toBeLessThan(180);
  });

  it('annualises once there is enough history', () => {
    const out = computeRiskStats(monthly([
      ['2024-01-01', 100], ['2024-07-01', 130], ['2025-01-01', 160], ['2026-01-01', 200],
    ]));
    expect(out.totalReturn).toBeCloseTo(100);      // doubled
    // Two calendar years, but 731 days: 2024 is a leap year. Annualising over a
    // 365-day year therefore gives slightly less than the 41.42% that "exactly
    // two years" would -- assert the relationship, not a rounded constant.
    expect(out.spanDays).toBe(731);
    expect(out.annualisedReturn).toBeCloseTo((2 ** (365 / 731) - 1) * 100, 6);
    expect(out.annualisedReturn).toBeGreaterThan(41.3);
    expect(out.annualisedReturn).toBeLessThan(41.42);
  });

  it('reports zero volatility for a perfectly flat index', () => {
    const out = computeRiskStats(idx([100, 100, 100, 100]));
    expect(out.annualisedVol).toBeCloseTo(0);
  });

  it('reports higher volatility for a choppier path to the same place', () => {
    const calm = computeRiskStats(idx([100, 101, 102, 103, 104]));
    const wild = computeRiskStats(idx([100, 120, 90, 115, 104]));
    expect(wild.annualisedVol).toBeGreaterThan(calm.annualisedVol);
  });

  it('measures Sharpe against the documented risk-free rate', () => {
    expect(RISK_FREE_RATE).toBeCloseTo(0.02);
    const out = computeRiskStats(monthly([
      ['2024-01-01', 100], ['2024-07-01', 110], ['2025-01-01', 120], ['2026-01-01', 130],
    ]));
    // Sharpe = (annualised return - rf) / annualised vol, all as fractions.
    expect(out.sharpe).toBeCloseTo(
      (out.annualisedReturn / 100 - RISK_FREE_RATE) / (out.annualisedVol / 100), 6);
  });

  it('picks the best and worst calendar month from month-end values', () => {
    const out = computeRiskStats(monthly([
      ['2025-01-31', 100], ['2025-02-28', 110],  // +10%
      ['2025-03-31', 99],                        // -10%
      ['2025-04-30', 108.9],                     // +10%
    ]));
    expect(out.bestMonth.ret).toBeCloseTo(10);
    expect(out.worstMonth.ret).toBeCloseTo(-10);
    expect(out.monthCount).toBe(3);
    expect(out.positiveMonthRate).toBeCloseTo(200 / 3);
  });
});

// ===========================================================================
describe('computeAllocation', () => {
  it('returns null when there is nothing to allocate', () => {
    expect(computeAllocation([], 0, 0)).toBeNull();
  });

  it('splits by asset class and sums to 100%', () => {
    const out = computeAllocation([holding('AAPL', 600)], 300, 100);
    expect(out.total).toBeCloseTo(1000);
    expect(out.basisLabel).toBe('net worth');
    const total = out.byClass.reduce((s, c) => s + c.weight, 0);
    expect(total).toBeCloseTo(100);
    expect(out.byClass.find((c) => c.key === 'stocks').weight).toBeCloseTo(60);
    expect(out.byClass.find((c) => c.key === 'bonds').weight).toBeCloseTo(30);
    expect(out.byClass.find((c) => c.key === 'cash').weight).toBeCloseTo(10);
  });

  it('omits an asset class that is empty rather than drawing a zero segment', () => {
    const out = computeAllocation([holding('AAPL', 1000)], 0, 0);
    expect(out.byClass.map((c) => c.key)).toEqual(['stocks']);
  });

  it('orders positions by value, largest first', () => {
    const out = computeAllocation(
      [holding('SMALL', 100), holding('BIG', 500), holding('MID', 300)], 0, 100);
    expect(out.positions.map((p) => p.key)).toEqual(['BIG', 'MID', 'SMALL']);
    expect(out.largest.key).toBe('BIG');
  });

  // The reciprocal of the Herfindahl index. Equal weights give back the position
  // count exactly, which is what makes the number legible.
  it('reports effective positions equal to the count when weights are equal', () => {
    const out = computeAllocation(
      ['A', 'B', 'C', 'D'].map((t) => holding(t, 250)), 0, 0);
    expect(out.effectivePositions).toBeCloseTo(4);
  });

  it('reports far fewer effective positions when one name dominates', () => {
    const out = computeAllocation(
      [holding('BIG', 900), holding('A', 25), holding('B', 25),
       holding('C', 25), holding('D', 25)], 0, 0);
    expect(out.effectivePositions).toBeLessThan(1.5);
    expect(out.positions.length).toBe(5);
  });

  it('sums the top five weights', () => {
    const out = computeAllocation(
      Array.from({ length: 10 }, (_, i) => holding(`T${i}`, 100)), 0, 0);
    expect(out.top5Weight).toBeCloseTo(50);
  });

  // A negative cash balance makes net worth smaller than what is invested, so
  // shares of it exceed 100% and overflow the bar. The denominator switches and
  // the panel says which one it used.
  it('switches the denominator to invested assets when cash is negative', () => {
    const out = computeAllocation([holding('AAPL', 1000)], 0, -100);
    expect(out.total).toBeCloseTo(900);            // net worth, still reported
    expect(out.basis).toBeCloseTo(1000);           // but weights use this
    expect(out.basisLabel).toBe('invested assets');
    expect(out.negativeCash).toBeCloseTo(-100);
    expect(out.positions[0].weight).toBeCloseTo(100);
  });

  it('reports no negative cash when the balance is positive', () => {
    const out = computeAllocation([holding('AAPL', 900)], 0, 100);
    expect(out.negativeCash).toBeNull();
    expect(out.basisLabel).toBe('net worth');
  });

  it('never treats a negative bond balance as a holding', () => {
    const out = computeAllocation([holding('AAPL', 1000)], -50, 0);
    expect(out.bondsValue).toBeCloseTo(0);
    expect(out.byClass.some((c) => c.key === 'bonds')).toBe(false);
  });
});

// ===========================================================================
describe('groupByMonth', () => {
  it('sums amounts into calendar months, in order', () => {
    expect(groupByMonth([
      { date: '2025-02-05', amount: 5 },
      { date: '2025-01-10', amount: 10 },
      { date: '2025-01-20', amount: 15 },
    ])).toEqual([
      { month: '2025-01', amount: 25 },
      { month: '2025-02', amount: 5 },
    ]);
  });

  it('takes the amount through a supplied accessor', () => {
    expect(groupByMonth(
      [{ date: '2025-01-10', net_amount: 7 }], (i) => i.net_amount,
    )).toEqual([{ month: '2025-01', amount: 7 }]);
  });

  it('returns nothing for no input', () => {
    expect(groupByMonth([])).toEqual([]);
  });
});
