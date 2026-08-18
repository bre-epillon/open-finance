// Builds daily portfolio value/return series from transactions + historical prices.
// Pure functions only -- no React, no fetching -- so both PortfolioEvolutionChart and
// PerformanceChart can derive their series from the same inputs without duplicating logic.

function buildPriceIndex(priceHistory) {
  const byTicker = {};
  priceHistory.forEach((r) => {
    const ticker = r.ticker.toUpperCase();
    const day = r.timestamp.slice(0, 10);
    if (!byTicker[ticker]) byTicker[ticker] = [];
    byTicker[ticker].push([day, r.close]);
  });
  Object.values(byTicker).forEach((pairs) => pairs.sort((a, b) => a[0].localeCompare(b[0])));
  return byTicker;
}

// Latest close on or before `day`. Prices are sparse (trading days only), so every
// other calculation forward-fills through this rather than requiring an exact match.
function lastValueOnOrBefore(sortedPairs, day) {
  let lo = 0, hi = sortedPairs.length - 1, result = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (sortedPairs[mid][0] <= day) {
      result = sortedPairs[mid][1];
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

// Sweeps every relevant date once, in order, accumulating shares/cash/bond cost basis
// as of that date. Bonds have no live price feed, so they're valued at cost basis
// (amount actually paid), not marked-to-market -- an explicit simplification, not a bug.
export function buildValueSeries({ transactions, bondTransactions, cashDeposits, interestPayments, priceHistory }) {
  const priceIndex = buildPriceIndex(priceHistory);

  const stockTx = [...transactions].sort((a, b) => a.date.localeCompare(b.date));
  const bondTx = [...bondTransactions].sort((a, b) => a.date.localeCompare(b.date));
  const deposits = [...cashDeposits].sort((a, b) => a.date.localeCompare(b.date));
  const interest = [...interestPayments].sort((a, b) => a.date.localeCompare(b.date));

  // The portfolio's history starts at its first real event (a trade, deposit, or
  // interest payment) -- not at however far back price history happens to exist for
  // whichever ticker has the longest inception date. Without this clamp, a fetched
  // price series for e.g. an old ETF would prepend years of flat zero-value days before
  // the portfolio actually existed.
  const eventDates = [
    ...stockTx.map((t) => t.date),
    ...bondTx.map((t) => t.date),
    ...deposits.map((d) => d.date),
    ...interest.map((p) => p.date),
  ];
  if (eventDates.length === 0) return [];
  const firstEventDate = eventDates.reduce((min, d) => (d < min ? d : min));

  const allDays = new Set(eventDates.filter((d) => d >= firstEventDate));
  Object.values(priceIndex).forEach((pairs) =>
    pairs.forEach(([day]) => {
      if (day >= firstEventDate) allDays.add(day);
    })
  );
  const days = Array.from(allDays).sort();

  const sharesByTicker = {};
  const costBasisByTicker = {};
  const bondCostBasisByIsin = {};
  let bondCostBasis = 0;
  let cash = 0;
  let cumulativeInterest = 0;
  // Every euro of totalValue attributes to exactly one of these buckets (see the
  // accounting identity below) -- that's what lets the performance chart isolate
  // "just my stock picks" from "income" from "trading gains" without double-counting.
  let netContributions = 0;   // cumulative deposits/transfers/bonuses minus card spend
  let cashInterestCum = 0;    // cumulative interest on idle cash
  let dividendsCum = 0;       // cumulative dividend income
  let bondsIncomeCum = 0;     // cumulative bond coupons + realized gain/loss from bond sales
  let selloffGainsCum = 0;    // cumulative realized gain/loss from stock sales
  let si = 0, bi = 0, di = 0, ii = 0;

  return days.map((day) => {
    while (si < stockTx.length && stockTx[si].date <= day) {
      const t = stockTx[si];
      const ticker = t.ticker.toUpperCase();
      // shares is negative on SELL rows in the source data (Trade Republic export
      // convention) -- usePortfolio.js's holdings calc already normalizes this with
      // Math.abs(), so this must match it or SELLs get double-counted backwards.
      const qty = Math.abs(parseFloat(t.quantity));
      const price = parseFloat(t.price);
      const prevShares = sharesByTicker[ticker] || 0;
      sharesByTicker[ticker] = prevShares + (t.type === 'BUY' ? qty : -qty);
      cash += t.type === 'BUY' ? -qty * price : qty * price;

      // Average-cost basis (mirrors usePortfolio.js's holdings calc). Serves two
      // purposes: a fallback value for days a held ticker has no price data yet (see
      // stocksValue below), and the baseline realized gain/loss is measured against.
      const cb = costBasisByTicker[ticker] || { totalCost: 0 };
      if (t.type === 'BUY') {
        cb.totalCost += qty * price;
      } else {
        const avgBuyPrice = prevShares > 0 ? cb.totalCost / prevShares : 0;
        const costOfSold = qty * avgBuyPrice;
        selloffGainsCum += qty * price - costOfSold;
        cb.totalCost -= costOfSold;
      }
      costBasisByTicker[ticker] = cb;
      si++;
    }
    while (bi < bondTx.length && bondTx[bi].date <= day) {
      const b = bondTx[bi];
      const isin = b.symbol;
      const amount = parseFloat(b.amount) || 0; // negative = buy, positive = sell
      const qty = Math.abs(parseFloat(b.shares)) || 0;
      const cb = bondCostBasisByIsin[isin] || { totalCost: 0, shares: 0 };
      if (b.type === 'BUY') {
        cb.totalCost += -amount;
        cb.shares += qty;
        bondCostBasis += -amount;
      } else {
        const avgCost = cb.shares > 0 ? cb.totalCost / cb.shares : 0;
        const costOfSold = avgCost * qty;
        bondsIncomeCum += amount - costOfSold; // realized gain/loss on the sold portion
        cb.totalCost -= costOfSold;
        cb.shares -= qty;
        bondCostBasis -= costOfSold;
      }
      bondCostBasisByIsin[isin] = cb;
      cash += amount;
      bi++;
    }
    while (di < deposits.length && deposits[di].date <= day) {
      cash += deposits[di].amount;
      netContributions += deposits[di].amount;
      di++;
    }
    while (ii < interest.length && interest[ii].date <= day) {
      const p = interest[ii];
      cash += p.net_amount;
      cumulativeInterest += p.net_amount;
      if (p.source === 'bond') bondsIncomeCum += p.net_amount;
      else if (p.source === 'dividend') dividendsCum += p.net_amount;
      else cashInterestCum += p.net_amount;
      ii++;
    }

    let stocksValue = 0;
    let stocksCostBasisHeld = 0;
    Object.entries(sharesByTicker).forEach(([ticker, shares]) => {
      if (shares <= 0.00001) return;
      const price = lastValueOnOrBefore(priceIndex[ticker] || [], day);
      const heldCost = costBasisByTicker[ticker].totalCost;
      stocksValue += price != null ? shares * price : heldCost;
      stocksCostBasisHeld += heldCost;
    });
    const stocksUnrealizedGain = stocksValue - stocksCostBasisHeld;

    const bondsValue = Math.max(bondCostBasis, 0);
    return {
      date: day,
      stocksValue,
      bondsValue,
      cash,
      cumulativeInterest,
      totalValue: stocksValue + bondsValue + cash,
      // totalValue === netContributions + cashInterestCum + dividendsCum + bondsIncomeCum
      //             + selloffGainsCum + stocksUnrealizedGain (see the derivation in the
      // performance chart's "how is this calculated" panel) -- these are what
      // buildPerformanceSeries's `components` selector picks from.
      netContributions,
      cashInterestCum,
      dividendsCum,
      bondsIncomeCum,
      selloffGainsCum,
      stocksUnrealizedGain,
    };
  });
}

export const ALL_COMPONENTS = { stocks: true, bonds: true, dividends: true, selloff: true };

// Which of totalValue's components to include, on top of the always-included baseline
// (net contributions + idle-cash interest -- your capital, not a "return"). Selecting
// none shows what a plain cash holding would have done; selecting all reproduces the
// full portfolio curve exactly (see the identity in buildValueSeries).
function selectedValue(point, components) {
  return (
    point.netContributions +
    point.cashInterestCum +
    (components.stocks ? point.stocksUnrealizedGain : 0) +
    (components.bonds ? point.bondsIncomeCum : 0) +
    (components.dividends ? point.dividendsCum : 0) +
    (components.selloff ? point.selloffGainsCum : 0)
  );
}

// Daily-chained time-weighted return, approximated by treating each day's external cash
// flow (deposits only -- interest is portfolio income, already inside `cash`) as landing
// before that day's return is measured. Fine for monthly, small-relative-to-portfolio
// flows like this one; a full Modified-Dietz weighting would be overkill here.
//
// The benchmark isn't a plain price index -- it simulates a shadow portfolio that
// received the exact same cash flows as the real one and spent every euro buying the
// benchmark that same day. A plain "SPY since day 0" index implicitly assumes a
// lump-sum investment that never happened, which is what made the comparison feel
// misleading against a portfolio that was actually funded gradually over time.
export function buildPerformanceSeries(valueSeries, cashDeposits, benchmarkHistory, components = ALL_COMPONENTS) {
  if (valueSeries.length === 0) return [];

  const depositsByDay = {};
  cashDeposits.forEach((d) => {
    depositsByDay[d.date] = (depositsByDay[d.date] || 0) + d.amount;
  });

  const benchPairs = Object.entries(
    benchmarkHistory.reduce((acc, r) => {
      acc[r.timestamp.slice(0, 10)] = r.close;
      return acc;
    }, {})
  ).sort((a, b) => a[0].localeCompare(b[0]));

  let portfolioIndex = 100;
  let prevValue = null;
  let benchmarkIndex = 100;
  let shadowShares = 0;
  let prevShadowValue = null;

  return valueSeries.map((point) => {
    const flow = depositsByDay[point.date] || 0;

    const value = selectedValue(point, components);
    if (prevValue !== null && prevValue > 0) {
      portfolioIndex *= 1 + (value - prevValue - flow) / prevValue;
    }
    prevValue = value;

    const benchPrice = lastValueOnOrBefore(benchPairs, point.date);
    if (benchPrice != null) {
      if (flow !== 0) shadowShares += flow / benchPrice;
      const shadowValue = shadowShares * benchPrice;
      if (prevShadowValue !== null && prevShadowValue > 0) {
        benchmarkIndex *= 1 + (shadowValue - prevShadowValue - flow) / prevShadowValue;
      }
      prevShadowValue = shadowValue;
    }

    return {
      date: point.date,
      portfolioIndex,
      benchmarkIndex: prevShadowValue != null ? benchmarkIndex : null,
    };
  });
}

export function downsampleSeries(series, maxPoints = 400) {
  if (series.length <= maxPoints) return series;
  const factor = Math.ceil(series.length / maxPoints);
  return series.filter((_, i) => i % factor === 0 || i === series.length - 1);
}
