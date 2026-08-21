// One place that decides how a number is rendered.
//
// Before this existed, every component hand-rolled
// `x.toLocaleString(undefined, { minimumFractionDigits: 2, ... })` -- 30-odd
// copies -- and half of them prefixed '$' while the portfolio charts prefixed
// '€'. The underlying account is EUR (Trade Republic), so EUR is the single
// display currency; see the CURRENCY note below for the one honest caveat.

// The transaction/deposit/coupon data is all EUR. yfinance closes for
// US-listed tickers are USD, so a US position's "last price" column and the
// Terminal's raw price chart are strictly speaking mixed-currency. That is a
// data problem (no FX series is ingested yet), not a formatting one -- it is
// tracked in REFACTORING.md. Until an FX rate lands, everything renders as EUR
// and `formatPrice` exists so those call sites are greppable.
export const CURRENCY = 'EUR';

const LOCALE = 'de-DE'; // 1.234,56 -- matches how a EUR account statement reads

const money = new Intl.NumberFormat(LOCALE, {
  style: 'currency',
  currency: CURRENCY,
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const plain = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const qty = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 4 });

export function formatCurrency(value) {
  if (value == null || Number.isNaN(value)) return '--';
  return money.format(value);
}

// Axis ticks and other tight spots. Intl's notation:'compact' is useless in
// de-DE -- CLDR has no thousands abbreviation for German, so 60000 comes back as
// "60.000,0 €", longer than the plain form. Hand-rolled instead.
const compactUnits = [
  [1e9, 'Mrd'],
  [1e6, 'M'],
  [1e3, 'k'],
];

export function formatCurrencyCompact(value) {
  if (value == null || Number.isNaN(value)) return '--';
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  for (const [scale, unit] of compactUnits) {
    if (abs >= scale) {
      const scaled = abs / scale;
      const digits = scaled < 10 ? 1 : 0;
      return `${sign}${scaled.toLocaleString(LOCALE, { maximumFractionDigits: digits })}${unit} €`;
    }
  }
  return `${sign}${Math.round(abs)} €`;
}

// Explicit '+' on gains, so a P&L figure never relies on colour alone to say
// which direction it went.
export function formatSigned(value) {
  if (value == null || Number.isNaN(value)) return '--';
  return `${value >= 0 ? '+' : '-'}${money.format(Math.abs(value))}`;
}

export function formatPercent(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return '--';
  return `${value.toFixed(digits)}%`;
}

export function formatSignedPercent(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return '--';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

export function formatQuantity(value) {
  if (value == null || Number.isNaN(value)) return '--';
  return qty.format(value);
}

// Market prices from yfinance. Same rendering as formatCurrency today; kept as
// its own function purely so the mixed-currency call sites stay findable.
export const formatPrice = formatCurrency;

export function formatNumber(value) {
  if (value == null || Number.isNaN(value)) return '--';
  return plain.format(value);
}

// '2026-08-21' -> 'Aug 2026', for month-bucketed axes.
export function formatMonthLabel(isoDay) {
  const [y, m] = isoDay.split('-');
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${MONTHS[Number(m) - 1]} ${y}`;
}
