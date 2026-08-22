// Spec for the portfolio value/return engine.
//
// This is the file BACKLOG.md and REFACTORING.md both flag as the highest-risk
// code in the repo: it produces plausible wrong numbers rather than errors, and
// three separate bugs were found in it by hand-diffing totals against expected
// values. Each of those three has a named test below, so the next change cannot
// reintroduce them silently.
//
// Read top to bottom as the specification for one module (Architecture.md
// exempts tests from the 200-line cap for exactly this reason).

import { describe, it, expect } from 'vitest';
import {
  buildValueSeries,
  buildPerformanceSeries,
  downsampleSeries,
  ALL_COMPONENTS,
} from './portfolioTimeSeries.js';

// --- fixture helpers -------------------------------------------------------
// Named builders rather than raw literals: a test that says `buy('AAPL', 10, 100)`
// states its intent, and the shapes below are the real ones from
// parsed_transactions.json / state_bonds.json / cash_deposits.json.

const tx = (date, ticker, type, quantity, price) => ({
  id: `${date}-${ticker}-${type}-${quantity}`,
  ticker, date, type, quantity, price, name: ticker,
});

const bond = (date, symbol, type, amount, shares) => ({
  date, symbol, type, amount: String(amount), shares: String(shares),
});

const deposit = (date, amount) => ({ id: `d-${date}-${amount}`, date, amount });

const income = (date, source, net_amount) => ({
  id: `i-${date}-${source}-${net_amount}`, date, source, net_amount,
});

const close = (date, ticker, price) => ({
  ticker, timestamp: `${date}T00:00:00.000000Z`, close: price,
});

// Every argument is required, so default them all to empty and override.
const build = (over = {}) => buildValueSeries({
  transactions: [], bondTransactions: [], cashDeposits: [],
  interestPayments: [], priceHistory: [], ...over,
});

const last = (series) => series[series.length - 1];

// The identity the whole design rests on. Every euro of totalValue attributes to
// exactly one bucket, which is what lets the performance chart isolate "just my
// stock picks" from "income" without double-counting. If this drifts, the
// component toggles are silently lying.
function expectIdentity(series) {
  series.forEach((p) => {
    const sum = p.netContributions + p.cashInterestCum + p.dividendsCum
      + p.bondsIncomeCum + p.selloffGainsCum + p.stocksUnrealizedGain;
    expect(p.totalValue).toBeCloseTo(sum, 6);
  });
}

// ===========================================================================
describe('buildValueSeries', () => {
  it('returns an empty series when nothing has happened', () => {
    expect(build()).toEqual([]);
  });

  it('values a held position at its most recent close', () => {
    const series = build({
      transactions: [tx('2025-01-02', 'AAPL', 'BUY', 10, 100)],
      cashDeposits: [deposit('2025-01-01', 1000)],
      priceHistory: [close('2025-01-02', 'AAPL', 100), close('2025-01-03', 'AAPL', 110)],
    });
    const end = last(series);
    expect(end.date).toBe('2025-01-03');
    expect(end.stocksValue).toBeCloseTo(1100);
    expect(end.cash).toBeCloseTo(0);            // 1000 deposited, 1000 spent
    expect(end.totalValue).toBeCloseTo(1100);
    expect(end.stocksUnrealizedGain).toBeCloseTo(100);
  });

  // BUG 1 of 3. The Trade Republic export carries a NEGATIVE quantity on sell
  // rows. usePortfolio.js normalises with Math.abs(); this module must match it
  // or a sale increases the position instead of reducing it.
  it('treats a SELL as a reduction even when the source quantity is negative', () => {
    const series = build({
      transactions: [
        tx('2025-01-02', 'AAPL', 'BUY', 10, 100),
        tx('2025-01-03', 'AAPL', 'SELL', -4, 150),
      ],
      cashDeposits: [deposit('2025-01-01', 2000)],
      priceHistory: [close('2025-01-02', 'AAPL', 100), close('2025-01-03', 'AAPL', 150)],
    });
    const end = last(series);
    expect(end.stocksValue).toBeCloseTo(900);         // 6 shares left, not 14
    expect(end.selloffGainsCum).toBeCloseTo(200);     // 4 x (150 - 100)
  });

  it('reports the same result whether a SELL quantity is signed or unsigned', () => {
    const of = (quantity) => last(build({
      transactions: [
        tx('2025-01-02', 'AAPL', 'BUY', 10, 100),
        tx('2025-01-03', 'AAPL', 'SELL', quantity, 150),
      ],
      priceHistory: [close('2025-01-03', 'AAPL', 150)],
    }));
    expect(of(-4).stocksValue).toBeCloseTo(of(4).stocksValue);
    expect(of(-4).selloffGainsCum).toBeCloseTo(of(4).selloffGainsCum);
  });

  // BUG 2 of 3. A recently-added ticker can be held for weeks before its
  // backfill lands. Valuing it at zero made net worth collapse; cost basis is
  // the honest approximation, and it keeps unrealised gain at exactly 0 rather
  // than inventing a loss equal to the whole position.
  it('falls back to cost basis for a held ticker with no price data', () => {
    const end = last(build({
      transactions: [tx('2025-01-02', 'NEW.DE', 'BUY', 5, 20)],
      priceHistory: [],
    }));
    expect(end.stocksValue).toBeCloseTo(100);
    expect(end.stocksUnrealizedGain).toBeCloseTo(0);
  });

  // BUG 3 of 3. Selling a bond before maturity realises proceeds MINUS the cost
  // of the portion sold. Booking the full proceeds as income overstated return
  // by the entire principal.
  it('measures a bond sale against its cost basis, not its proceeds', () => {
    const end = last(build({
      bondTransactions: [
        bond('2025-01-02', 'IT0005340929', 'BUY', -1000, 1000),
        bond('2025-06-02', 'IT0005340929', 'SELL', 1100, 1000),
      ],
    }));
    expect(end.bondsIncomeCum).toBeCloseTo(100);   // the gain, not 1100
    expect(end.bondsValue).toBeCloseTo(0);         // position fully closed
  });

  it('holds an unsold bond at cost and books its coupons as income', () => {
    const end = last(build({
      bondTransactions: [bond('2025-01-02', 'IT0005340929', 'BUY', -1000, 1000)],
      interestPayments: [income('2025-07-01', 'bond', 25)],
    }));
    expect(end.bondsValue).toBeCloseTo(1000);
    expect(end.bondsIncomeCum).toBeCloseTo(25);
  });

  it('splits income into cash interest, dividends and bond coupons', () => {
    const end = last(build({
      cashDeposits: [deposit('2025-01-01', 1000)],
      interestPayments: [
        income('2025-02-01', 'cash', 5),
        income('2025-03-01', 'dividend', 7),
        income('2025-04-01', 'bond', 11),
      ],
    }));
    expect(end.cashInterestCum).toBeCloseTo(5);
    expect(end.dividendsCum).toBeCloseTo(7);
    expect(end.bondsIncomeCum).toBeCloseTo(11);
    expect(end.cumulativeInterest).toBeCloseTo(23);
    expect(end.cash).toBeCloseTo(1023);
  });

  it('starts at the first real event, not at the start of price history', () => {
    const series = build({
      transactions: [tx('2025-01-02', 'AAPL', 'BUY', 1, 100)],
      priceHistory: [
        close('2020-01-02', 'AAPL', 50),   // years before the portfolio existed
        close('2025-01-02', 'AAPL', 100),
      ],
    });
    expect(series[0].date).toBe('2025-01-02');
    expect(series.some((p) => p.date < '2025-01-02')).toBe(false);
  });

  it('forward-fills the last close through days with no price', () => {
    const series = build({
      transactions: [tx('2025-01-02', 'AAPL', 'BUY', 10, 100)],
      // A deposit on the 6th creates a series day; there is no close for it.
      cashDeposits: [deposit('2025-01-06', 0)],
      priceHistory: [close('2025-01-02', 'AAPL', 100), close('2025-01-03', 'AAPL', 120)],
    });
    expect(last(series).date).toBe('2025-01-06');
    expect(last(series).stocksValue).toBeCloseTo(1200);   // still the 03 close
  });

  it('keeps the accounting identity exact at every point', () => {
    expectIdentity(build({
      transactions: [
        tx('2025-01-02', 'AAPL', 'BUY', 10, 100),
        tx('2025-02-02', 'MSFT', 'BUY', 5, 200),
        tx('2025-03-02', 'AAPL', 'SELL', -4, 150),
        tx('2025-04-02', 'NOPRICE.DE', 'BUY', 3, 40),
      ],
      bondTransactions: [
        bond('2025-01-15', 'IT0005340929', 'BUY', -1000, 1000),
        bond('2025-05-15', 'IT0005340929', 'SELL', 520, 500),
      ],
      cashDeposits: [deposit('2025-01-01', 5000), deposit('2025-03-01', -250)],
      interestPayments: [
        income('2025-02-01', 'cash', 12),
        income('2025-03-15', 'dividend', 9),
        income('2025-04-15', 'bond', 14),
      ],
      priceHistory: [
        close('2025-01-02', 'AAPL', 100), close('2025-03-02', 'AAPL', 150),
        close('2025-06-02', 'AAPL', 160),
        close('2025-02-02', 'MSFT', 200), close('2025-06-02', 'MSFT', 180),
      ],
    }));
  });

  it('is unaffected by the order transactions arrive in', () => {
    const rows = [
      tx('2025-03-02', 'AAPL', 'SELL', 4, 150),
      tx('2025-01-02', 'AAPL', 'BUY', 10, 100),
    ];
    const prices = [close('2025-01-02', 'AAPL', 100), close('2025-03-02', 'AAPL', 150)];
    const forward = last(build({ transactions: rows, priceHistory: prices }));
    const reversed = last(build({ transactions: [...rows].reverse(), priceHistory: prices }));
    expect(forward.stocksValue).toBeCloseTo(reversed.stocksValue);
    expect(forward.selloffGainsCum).toBeCloseTo(reversed.selloffGainsCum);
  });
});

// ===========================================================================
describe('buildPerformanceSeries', () => {
  const flatDeposits = [deposit('2025-01-02', 1000), deposit('2025-01-03', 1000)];

  it('returns an empty series for an empty value series', () => {
    expect(buildPerformanceSeries([], [], [])).toEqual([]);
  });

  // The single most important property in the module. Funding the account is
  // not a return; if this breaks, every performance figure flatters the
  // portfolio in proportion to how much was paid in.
  it('does not report a deposit as a gain', () => {
    const series = buildPerformanceSeries(
      build({ cashDeposits: flatDeposits }), flatDeposits, []);
    series.forEach((p) => expect(p.portfolioIndex).toBeCloseTo(100));
  });

  it('reports a real price move as a gain', () => {
    const deposits = [deposit('2025-01-01', 1000)];
    const valueSeries = build({
      transactions: [tx('2025-01-02', 'AAPL', 'BUY', 10, 100)],
      cashDeposits: deposits,
      priceHistory: [close('2025-01-02', 'AAPL', 100), close('2025-01-03', 'AAPL', 110)],
    });
    const series = buildPerformanceSeries(valueSeries, deposits, []);
    // +100 of unrealised gain on 1000 of capital.
    expect(last(series).portfolioIndex).toBeCloseTo(110, 4);
  });

  it('shows a flat line when every component is switched off', () => {
    const deposits = [deposit('2025-01-01', 1000)];
    const valueSeries = build({
      transactions: [tx('2025-01-02', 'AAPL', 'BUY', 10, 100)],
      cashDeposits: deposits,
      priceHistory: [close('2025-01-02', 'AAPL', 100), close('2025-01-03', 'AAPL', 110)],
    });
    const none = { stocks: false, bonds: false, dividends: false, selloff: false };
    const series = buildPerformanceSeries(valueSeries, deposits, [], none);
    series.forEach((p) => expect(p.portfolioIndex).toBeCloseTo(100));
  });

  it('attributes a gain to the component that produced it', () => {
    const deposits = [deposit('2025-01-01', 1000)];
    const valueSeries = build({
      cashDeposits: deposits,
      interestPayments: [income('2025-02-01', 'dividend', 50)],
    });
    const withDiv = last(buildPerformanceSeries(valueSeries, deposits, [], ALL_COMPONENTS));
    const without = last(buildPerformanceSeries(
      valueSeries, deposits, [], { ...ALL_COMPONENTS, dividends: false }));
    expect(withDiv.portfolioIndex).toBeCloseTo(105, 4);
    expect(without.portfolioIndex).toBeCloseTo(100, 4);
  });

  it('leaves the benchmark null until it has a price', () => {
    const series = buildPerformanceSeries(
      build({ cashDeposits: flatDeposits }), flatDeposits, []);
    series.forEach((p) => expect(p.benchmarkIndex).toBeNull());
  });

  // The benchmark is a shadow portfolio that received the same flows on the
  // same days -- not a plain "price since day one" index, which would assume a
  // lump sum that was never invested.
  it('gives the benchmark the same cash flows, so deposits are not gains there either', () => {
    const deposits = [deposit('2025-01-02', 1000), deposit('2025-01-03', 1000)];
    const series = buildPerformanceSeries(
      build({ cashDeposits: deposits }), deposits,
      [close('2025-01-02', 'SPY', 100), close('2025-01-03', 'SPY', 100)]);
    series.forEach((p) => expect(p.benchmarkIndex).toBeCloseTo(100));
  });

  it('tracks the benchmark price once the shadow portfolio is funded', () => {
    const deposits = [deposit('2025-01-02', 1000)];
    // The portfolio is deliberately flat (bought at 100, still 100) and exists
    // on both days, so the only thing moving is the benchmark. Note that the
    // value series has to span both days for the benchmark to be reported on
    // the second one -- buildPerformanceSeries walks the value series, so a
    // lone deposit would give it a single day to report on.
    const valueSeries = build({
      cashDeposits: deposits,
      transactions: [tx('2025-01-02', 'AAPL', 'BUY', 10, 100)],
      priceHistory: [close('2025-01-02', 'AAPL', 100), close('2025-01-03', 'AAPL', 100)],
    });
    expect(valueSeries.map((p) => p.date)).toEqual(['2025-01-02', '2025-01-03']);

    const series = buildPerformanceSeries(valueSeries, deposits,
      [close('2025-01-02', 'SPY', 100), close('2025-01-03', 'SPY', 200)]);
    expect(last(series).portfolioIndex).toBeCloseTo(100, 4);   // flat
    expect(last(series).benchmarkIndex).toBeCloseTo(200, 4);   // doubled
  });
});

// ===========================================================================
describe('downsampleSeries', () => {
  const series = (n) => Array.from({ length: n }, (_, i) => ({ date: `d${i}`, i }));

  it('returns the input untouched when it is already short enough', () => {
    const s = series(10);
    expect(downsampleSeries(s, 400)).toBe(s);
  });

  it('thins a long series to about the requested size', () => {
    const out = downsampleSeries(series(4000), 400);
    expect(out.length).toBeLessThanOrEqual(401);
    expect(out.length).toBeGreaterThan(300);
  });

  it('always keeps the first and last point', () => {
    const s = series(1001);
    const out = downsampleSeries(s, 100);
    expect(out[0]).toBe(s[0]);
    expect(out[out.length - 1]).toBe(s[s.length - 1]);
  });
});
