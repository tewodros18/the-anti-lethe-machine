import { describe, expect, it } from 'vitest';
import { dateTickIndices, formatTick, niceTicks, thin, tickPrecision } from '$lib/charts/ticks';

describe('niceTicks', () => {
	it('uses round steps from the 1/2/5/10 progression', () => {
		expect(niceTicks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
		expect(niceTicks(0, 1, 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
	});

	it('covers the range it is given', () => {
		const ticks = niceTicks(0, 0.37, 5);
		expect(ticks[0]).toBeGreaterThanOrEqual(0);
		expect(ticks[ticks.length - 1]).toBeLessThanOrEqual(0.37);
		expect(ticks.length).toBeGreaterThan(1);
	});

	it('does not accumulate floating point drift', () => {
		for (const value of niceTicks(0, 1, 10)) {
			// Repeated addition of 0.1 would produce 0.30000000000000004.
			expect(value).toBe(Number(value.toPrecision(12)));
		}
	});

	it('handles a zero-width range', () => {
		expect(niceTicks(5, 5)).toEqual([5]);
	});

	it('handles a reversed range', () => {
		expect(niceTicks(10, 0, 5)).toEqual(niceTicks(0, 10, 5));
	});

	it('returns nothing for non-finite input', () => {
		expect(niceTicks(Number.NaN, 1)).toEqual([]);
		expect(niceTicks(0, Number.POSITIVE_INFINITY)).toEqual([]);
	});

	it('returns nothing when asked for no ticks', () => {
		expect(niceTicks(0, 1, 0)).toEqual([]);
	});

	it('works on very small ranges, as distances are', () => {
		const ticks = niceTicks(0, 0.004, 4);
		expect(ticks.length).toBeGreaterThan(1);
		expect(new Set(ticks).size).toBe(ticks.length);
	});

	it('works on large ranges, as latencies are', () => {
		const ticks = niceTicks(0, 48000, 5);
		expect(ticks.length).toBeGreaterThan(1);
		expect(ticks[ticks.length - 1]).toBeLessThanOrEqual(48000);
	});
});

describe('thin', () => {
	it('returns everything when it already fits', () => {
		expect(thin([1, 2, 3], 5)).toEqual([1, 2, 3]);
	});

	it('always keeps the first and last item', () => {
		const days = Array.from({ length: 83 }, (_, i) => i);
		const kept = thin(days, 7);
		expect(kept[0]).toBe(0);
		expect(kept[kept.length - 1]).toBe(82);
		expect(kept.length).toBeLessThanOrEqual(7);
	});

	it('spaces items evenly', () => {
		expect(thin([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3)).toEqual([0, 5, 10]);
	});

	it('never repeats an item', () => {
		for (let length = 1; length < 30; length += 1) {
			for (let max = 1; max < 10; max += 1) {
				const kept = thin(
					Array.from({ length }, (_, i) => i),
					max
				);
				expect(new Set(kept).size).toBe(kept.length);
			}
		}
	});

	it('returns the last item when only one is allowed', () => {
		expect(thin([1, 2, 3], 1)).toEqual([3]);
	});

	it('returns nothing when none are allowed', () => {
		expect(thin([1, 2, 3], 0)).toEqual([]);
	});

	it('handles an empty input', () => {
		expect(thin([], 5)).toEqual([]);
	});
});

describe('dateTickIndices', () => {
	it('returns indices within range', () => {
		const indices = dateTickIndices(83, 7);
		expect(indices.length).toBeLessThanOrEqual(7);
		for (const i of indices) {
			expect(i).toBeGreaterThanOrEqual(0);
			expect(i).toBeLessThan(83);
		}
	});

	it('handles an empty series', () => {
		expect(dateTickIndices(0)).toEqual([]);
	});

	it('is ascending', () => {
		const indices = dateTickIndices(40, 6);
		expect([...indices].sort((a, b) => a - b)).toEqual(indices);
	});
});

describe('tickPrecision', () => {
	it('uses no decimals for whole-number steps', () => {
		expect(tickPrecision([0, 2, 4])).toBe(0);
	});

	it('uses enough decimals that labels differ', () => {
		expect(tickPrecision([0, 0.002, 0.004])).toBeGreaterThanOrEqual(3);
	});

	it('formats consistently across a tick set', () => {
		const ticks = [0, 0.05, 0.1];
		const labels = ticks.map((t) => formatTick(t, ticks));
		expect(new Set(labels).size).toBe(ticks.length);
		expect(labels).toEqual(['0.00', '0.05', '0.10']);
	});

	it('does not collapse small distinct ticks into one label', () => {
		const ticks = niceTicks(0, 0.01, 5);
		const labels = ticks.map((t) => formatTick(t, ticks));
		expect(new Set(labels).size).toBe(ticks.length);
	});
});
