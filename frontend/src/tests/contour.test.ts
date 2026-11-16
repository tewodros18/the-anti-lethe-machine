/**
 * The hero contour field is deterministic, nearly round at the centre and
 * bent at the edge, so server and client render the same markup and the
 * drawing says what the caption says.
 */

import { describe, expect, it } from 'vitest';

import { contours, wobble } from '../lib/data/contour';

const PHASES: [number, number, number] = [0.3, 1.1, 2.4];

describe('wobble', () => {
	it('is exactly round with no drift and bends with it', () => {
		for (const theta of [0, 1, 2, 3, 4, 5, 6]) {
			expect(wobble(theta, 0, PHASES)).toBe(1);
		}
		const spread = (drift: number) => {
			let lo = Infinity;
			let hi = -Infinity;
			for (let i = 0; i < 360; i++) {
				const w = wobble((i / 360) * 2 * Math.PI, drift, PHASES);
				lo = Math.min(lo, w);
				hi = Math.max(hi, w);
			}
			return hi - lo;
		};
		expect(spread(0.3)).toBeLessThan(spread(1));
		// The strongest bend stays well short of folding the ring over itself.
		expect(spread(1)).toBeLessThan(0.5);
	});
});

describe('contours', () => {
	const opts = { count: 12, cx: 100, cy: 80, r0: 10, step: 8 };

	it('is deterministic for a seed and differs between seeds', () => {
		const a = contours({ ...opts, seed: 7 });
		const b = contours({ ...opts, seed: 7 });
		const c = contours({ ...opts, seed: 8 });
		expect(a).toEqual(b);
		expect(a).not.toEqual(c);
	});

	it('returns the requested rings, indexed from the centre, as closed paths', () => {
		const rings = contours(opts);
		expect(rings).toHaveLength(12);
		rings.forEach((ring, i) => {
			expect(ring.k).toBe(i);
			expect(ring.d.startsWith('M')).toBe(true);
			expect(ring.d.endsWith(' Z')).toBe(true);
			expect(ring.d.split(' L')).toHaveLength(180);
		});
	});

	it('drifts more the further a ring is from the centre', () => {
		const rings = contours(opts);
		expect(rings[0].drift).toBe(0);
		expect(rings[11].drift).toBe(1);
		for (let i = 1; i < rings.length; i++) {
			expect(rings[i].drift).toBeGreaterThan(rings[i - 1].drift);
		}
	});

	it('keeps the innermost ring round to the nearest tenth of a unit', () => {
		const [inner] = contours(opts);
		const radii = inner.d
			.replace(' Z', '')
			.split(/ (?=[ML])/)
			.map((v) => {
				const [x, y] = v.slice(1).split(/\s+/);
				return Math.hypot(Number(x) - 100, Number(y) - 80);
			});
		for (const r of radii) expect(r).toBeCloseTo(10, 0);
	});
});
