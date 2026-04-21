import { describe, it, expect } from 'vitest';
import { VERSION } from '../src/splitsmart-card';

describe('smoke', () => {
  it('exports a version string', () => {
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });
});
