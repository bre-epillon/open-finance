import React from 'react';

export default function PerformanceExplainer() {
  return (
    <details className="panel glass" style={{ padding: '1rem 1.35rem', marginTop: '0.75rem' }}>
      <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
        How is this calculated?
      </summary>
      <div className="text-muted text-sm" style={{ marginTop: '0.75rem', lineHeight: 1.6 }}>
        <p>
          <strong>Your Portfolio</strong> is a daily time-weighted return. Each day, your
          total value (stocks at market price, bonds at cost, plus cash) is compared to
          the day before, after removing that day's external cash flows -- deposits,
          transfers and bonuses in, card spending out -- so contributing money never
          reads as a gain. The result is chained day over day into an index starting at 100.
        </p>
        <p>
          <strong>Include</strong> toggles let you isolate where that return comes from.
          The baseline (always on) is your net contributed capital plus interest on idle
          cash. <em>Stocks</em> adds the unrealized gain/loss on positions you currently
          hold; <em>Bonds</em> adds coupon income plus any realized gain/loss from selling
          a bond before maturity; <em>Dividends</em> adds dividend income received;
          <em> Selloff Gains</em> adds realized gain/loss from selling stocks. Turning
          everything off shows what your money would look like had it just sat in cash;
          turning everything on reproduces the full portfolio curve.
        </p>
        <p>
          <strong>The benchmark</strong> isn't a plain "price since day one" index -- that
          would implicitly assume a lump-sum investment you never actually made. Instead it
          simulates a shadow portfolio that received your exact same deposits and
          withdrawals, on the exact same days, and immediately bought the benchmark with
          each one. That's the fair comparison for money that arrived gradually.
        </p>
        <p>
          <strong>Caveats:</strong> bonds have no live pricing feed, so their contribution
          here is income (coupons and realized gains), not day-to-day price moves. A few
          recently-added tickers without enough backfilled price history yet are valued at
          cost until more history is available, which can slightly understate unrealized
          gains until the backfill catches up.
        </p>
      </div>
    </details>
  );
}
