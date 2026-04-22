import { describe, it, expect } from 'vitest';
import { formatAbs, formatAmount, parseAmount, resolveLocale } from '../../src/util/currency';

describe('formatAmount', () => {
  it('formats GBP with £ symbol', () => {
    expect(formatAmount(82.4, 'GBP', 'en-GB')).toBe('£82.40');
  });

  it('pads to 2dp', () => {
    expect(formatAmount(82, 'GBP', 'en-GB')).toBe('£82.00');
  });

  it('uses thousands separator', () => {
    expect(formatAmount(1234567.89, 'GBP', 'en-GB')).toBe('£1,234,567.89');
  });

  it('handles negative', () => {
    expect(formatAmount(-45.45, 'GBP', 'en-GB')).toBe('-£45.45');
  });

  it('formats EUR', () => {
    expect(formatAmount(10, 'EUR', 'en-GB')).toMatch(/€10\.00/);
  });

  it('returns em-dash for non-finite', () => {
    expect(formatAmount(NaN, 'GBP', 'en-GB')).toBe('—');
    expect(formatAmount(Infinity, 'GBP', 'en-GB')).toBe('—');
  });
});

describe('formatAbs', () => {
  it('strips the minus sign', () => {
    expect(formatAbs(-45.45, 'GBP', 'en-GB')).toBe('£45.45');
  });

  it('leaves positive unchanged', () => {
    expect(formatAbs(45.45, 'GBP', 'en-GB')).toBe('£45.45');
  });
});

describe('parseAmount', () => {
  it('returns null for empty', () => {
    expect(parseAmount('')).toBeNull();
    expect(parseAmount('   ')).toBeNull();
  });

  it('parses plain numbers', () => {
    expect(parseAmount('82.4')).toBe(82.4);
    expect(parseAmount('82')).toBe(82);
  });

  it('strips comma group separators', () => {
    expect(parseAmount('1,234.56')).toBe(1234.56);
  });

  it('strips currency symbol prefix', () => {
    expect(parseAmount('£82.40')).toBe(82.4);
  });

  it('rounds to 2dp', () => {
    expect(parseAmount('1.234')).toBe(1.23);
    expect(parseAmount('1.239')).toBe(1.24);
  });

  it('returns null for nonsense', () => {
    expect(parseAmount('nope')).toBeNull();
    expect(parseAmount('-')).toBeNull();
    expect(parseAmount('.')).toBeNull();
  });
});

describe('resolveLocale', () => {
  it('defaults to en-GB', () => {
    expect(resolveLocale()).toBe('en-GB');
    expect(resolveLocale(null)).toBe('en-GB');
    expect(resolveLocale('')).toBe('en-GB');
  });

  it('passes through provided locale', () => {
    expect(resolveLocale('de-DE')).toBe('de-DE');
  });
});
