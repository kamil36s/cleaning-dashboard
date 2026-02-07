import { describe, it, expect } from 'vitest';
import { tempColor } from '../js/temp-scale.js';

describe('Temperature scale (WHY: sensor colors must be consistent)', () => {
  it('uses coldest stop below minimum', () => {
    expect(tempColor(-100)).toBe('#2F2C7E');
  });

  it('uses hottest stop above maximum', () => {
    expect(tempColor(50)).toBe('#B11226');
  });

  it('returns exact color on a defined stop', () => {
    expect(tempColor(20)).toBe('#f0e68c');
  });
});
