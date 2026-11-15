/**
 * The hero stipple is deterministic and stays inside its box, so server and
 * client render the same markup and nothing is drawn off the canvas.
 */

import { describe, expect, it } from 'vitest';

import { moundProfile, stipple } from '../lib/data/stipple';

describe('moundProfile', () => {
	it('peaks at the crest and falls away on both sides', () => {
		expect(moundProfile(0.62)).toBeCloseTo(1);
		expect(moundProfile(0.1)).toBeLessThan(moundProfile(0.4));
		expect(moundProfile(0.95)).toBeLessThan(moundProfile(0.7));
	});
});

describe('stipple', () => {
	it('is deterministic for a seed and differs between seeds', () => {
		const a = stipple(200, 100, 50, 7);
		const b = stipple(200, 100, 50, 7);
		const c = stipple(200, 100, 50, 8);
		expect(a).toEqual(b);
		expect(a).not.toEqual(c);
	});
	it('returns exactly the requested number of dots, all inside the box', () => {
		const dots = stipple(500, 120, 60, 3);
		expect(dots).toHaveLength(500);
		for (const dot of dots) {
			expect(dot.x).toBeGreaterThanOrEqual(0);
			expect(dot.x).toBeLessThanOrEqual(120);
			expect(dot.y).toBeGreaterThanOrEqual(0);
			expect(dot.y).toBeLessThanOrEqual(60);
			expect(dot.r).toBeGreaterThan(0);
		}
	});
	it('is denser near the base than near the crest', () => {
		const dots = stipple(2000, 100, 100, 5);
		const low = dots.filter((d) => d.y > 80).length;
		const high = dots.filter((d) => d.y < 20).length;
		expect(low).toBeGreaterThan(high * 3);
	});
});
