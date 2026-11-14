/**
 * Number and date formatting.
 *
 * `EM_DASH` is the single rendering for every null in the dataset. A null means
 * "not supplied" or "not enough data to say", and showing it as 0, 0.000 or an
 * empty cell would all read as a measurement. This is the one place that
 * decision lives.
 */

export const EM_DASH = '—';

/** A distance, hedge rate or other small magnitude. */
export function fmt(value: number | null | undefined, digits = 3): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	return value.toFixed(digits);
}

/** A ratio, rendered with a trailing multiplication sign. */
export function fmtRatio(value: number | null | undefined, digits = 2): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	return `${value.toFixed(digits)}×`;
}

/** A whole number with thousands separators. */
export function fmtInt(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	return Math.round(value).toLocaleString('en-US');
}

/** A count of words, rounded. */
export function fmtWords(value: number | null | undefined): string {
	return fmtInt(value);
}

/** A percentage from a 0–1 fraction. */
export function fmtPct(value: number | null | undefined, digits = 1): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	return `${(value * 100).toFixed(digits)}%`;
}

/** Milliseconds as seconds. */
export function fmtMs(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	if (value < 1000) return `${Math.round(value)} ms`;
	return `${(value / 1000).toFixed(1)} s`;
}

/** A cost in US dollars, with enough places to be non-zero. */
export function fmtCost(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	if (value === 0) return '$0';
	if (value < 0.01) return `$${value.toFixed(5)}`;
	return `$${value.toFixed(3)}`;
}

/** A per-token price, which is quoted in very small numbers. */
export function fmtPrice(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	if (value === 0) return '$0';
	// Prices are per token; per-million is the readable unit.
	return `$${(value * 1_000_000).toFixed(2)}/M`;
}

/** A byte count. */
export function fmtBytes(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
	if (value < 1024) return `${value} B`;
	if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
	return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Parse a `YYYY-MM-DD` day as a UTC date, avoiding local-timezone drift. */
export function parseDay(day: string): Date {
	const [y, m, d] = day.split('-').map(Number);
	return new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
}

/** `2026-10-08` -> `8 Oct`. */
export function shortDay(value: Date | string | number): string {
	const date =
		value instanceof Date ? value : typeof value === 'number' ? new Date(value) : parseDay(value);
	return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

/** `2026-10-08` -> `8 Oct 2026`. */
export function longDay(value: Date | string): string {
	const date = value instanceof Date ? value : parseDay(value);
	return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

/** An ISO timestamp as a readable UTC moment. */
export function fmtTimestamp(iso: string): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return iso;
	const hh = String(date.getUTCHours()).padStart(2, '0');
	const mm = String(date.getUTCMinutes()).padStart(2, '0');
	return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

/** First 12 characters of a hash, for display. */
export function shortHash(hash: string | null | undefined): string {
	if (!hash) return EM_DASH;
	return hash.slice(0, 12);
}

/** Vendor portion of a model id (`deepseek/deepseek-chat` -> `deepseek`). */
export function vendorOf(modelId: string): string {
	return modelId.split('/')[0] ?? modelId;
}

/** Model id without its vendor prefix, for compact axis labels. */
export function shortModel(modelId: string): string {
	const parts = modelId.split('/');
	return parts.length > 1 ? parts.slice(1).join('/') : modelId;
}
