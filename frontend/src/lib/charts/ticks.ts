/**
 * Tick generation and label thinning. Pure functions, unit tested.
 *
 * Kept out of the chart components because axis arithmetic is the part most
 * worth testing and the part least worth reasoning about inside markup.
 */

/**
 * Round tick values covering `[min, max]`, at most `count`-ish of them.
 *
 * Uses the 1 / 2 / 5 / 10 progression, so the steps are numbers a reader
 * recognises rather than whatever the data's range divided by five happens to
 * be.
 */
export function niceTicks(min: number, max: number, count = 5): number[] {
	if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
	if (count < 1) return [];
	if (min === max) return [min];
	if (min > max) [min, max] = [max, min];

	const span = max - min;
	const rawStep = span / count;
	const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
	const normalized = rawStep / magnitude;

	let step: number;
	if (normalized <= 1) step = magnitude;
	else if (normalized <= 2) step = 2 * magnitude;
	else if (normalized <= 5) step = 5 * magnitude;
	else step = 10 * magnitude;

	const first = Math.ceil(min / step) * step;
	const out: number[] = [];
	// Guard against floating-point overshoot at the top of the range.
	for (let value = first; value <= max + step * 1e-9; value += step) {
		// Re-round each value: repeated addition of 0.1 drifts.
		out.push(Number((Math.round(value / step) * step).toPrecision(12)));
	}
	return out;
}

/**
 * Pick at most `max` evenly spaced items, always keeping the first and last.
 *
 * Used for date axes, where the honest options are to thin the labels or to
 * overlap them.
 */
export function thin<T>(items: readonly T[], max: number): T[] {
	if (max < 1) return [];
	if (items.length <= max) return [...items];
	if (max === 1) return [items[items.length - 1]];

	const out: T[] = [];
	const step = (items.length - 1) / (max - 1);
	for (let i = 0; i < max; i += 1) {
		out.push(items[Math.round(i * step)]);
	}
	// Rounding can land twice on the same index at small sizes.
	return out.filter((item, i) => i === 0 || item !== out[i - 1]);
}

/**
 * Indices of the dates to label on a time axis.
 *
 * Returns indices rather than values so a caller can keep its own date objects.
 */
export function dateTickIndices(length: number, max = 7): number[] {
	if (length <= 0) return [];
	return thin(
		Array.from({ length }, (_, i) => i),
		max
	);
}

/** How many decimal places a tick set needs so no two labels read the same. */
export function tickPrecision(ticks: readonly number[]): number {
	if (ticks.length < 2) return ticks.length === 1 && Number.isInteger(ticks[0]) ? 0 : 2;
	const step = Math.abs(ticks[1] - ticks[0]);
	if (step === 0) return 2;
	if (step >= 1) return 0;
	return Math.min(6, Math.ceil(-Math.log10(step)));
}

/** Format a tick value with the precision its step implies. */
export function formatTick(value: number, ticks: readonly number[]): string {
	return value.toFixed(tickPrecision(ticks));
}
