import { describe, it, expect } from 'vitest';
import {
  currentMonth,
  formatMonthLabel,
  formatRelativeDate,
  parseDate,
  recentMonths,
} from '../../src/util/date';

const NOW = new Date(2026, 3, 21); // 2026-04-21

describe('parseDate', () => {
  it('parses YYYY-MM-DD to local Date', () => {
    const d = parseDate('2026-04-15');
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(3);
    expect(d.getDate()).toBe(15);
  });
});

describe('formatRelativeDate', () => {
  it('Today for same day', () => {
    expect(formatRelativeDate('2026-04-21', NOW)).toBe('Today');
  });

  it('Yesterday for previous day', () => {
    expect(formatRelativeDate('2026-04-20', NOW)).toBe('Yesterday');
  });

  it('weekday for 2-6 days ago', () => {
    expect(formatRelativeDate('2026-04-19', NOW)).toBe('Sunday');
  });

  it('"15 Apr" for same year', () => {
    expect(formatRelativeDate('2026-01-15', NOW, 'en-GB')).toBe('15 Jan');
  });

  it('"15 Apr 2025" for prior year beyond 365 days', () => {
    expect(formatRelativeDate('2024-11-15', NOW, 'en-GB')).toBe('15 Nov 2024');
  });
});

describe('formatMonthLabel', () => {
  it('formats as Month Year', () => {
    expect(formatMonthLabel('2026-04', 'en-GB')).toBe('April 2026');
  });
});

describe('recentMonths', () => {
  it('returns N months in reverse-chronological order', () => {
    const months = recentMonths(3, NOW);
    expect(months).toEqual(['2026-04', '2026-03', '2026-02']);
  });

  it('handles year wrap', () => {
    const months = recentMonths(4, new Date(2026, 1, 15)); // Feb
    expect(months).toEqual(['2026-02', '2026-01', '2025-12', '2025-11']);
  });
});

describe('currentMonth', () => {
  it('pads month to 2 digits', () => {
    expect(currentMonth(new Date(2026, 0, 1))).toBe('2026-01');
    expect(currentMonth(new Date(2026, 9, 1))).toBe('2026-10');
  });
});
