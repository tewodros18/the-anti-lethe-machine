/**
 * The register's headline findings, ranked from the index.
 *
 * Two lists, both pure functions of the index so they are testable and so the
 * home page states nothing the exported data does not contain:
 *
 * - regime changes: the changepoint detector's breaks in a model's own
 *   day-to-day noise, largest first, each tagged with the recorded event it
 *   coincides with (a host switch, a rebuild) or with no recorded cause;
 * - unstable pairs: the (question, model) cells whose mean adjacent-day
 *   distance is highest, largest first, among cells with enough pairs that a
 *   single odd day cannot produce the ranking.
 *
 * Each finding carries the compare-page selection that shows it: the question,
 * the model and two kept snapshot days bracketing the event. The link itself is
 * assembled by the component, because only the component knows the base path.
 */

import type { Changepoint, Index, InstabilityCell } from './types';

export interface CompareSelection {
	question: string;
	model: string;
	dayA: string;
	dayB: string;
}

export interface RegimeFinding {
	changepoint: Changepoint;
	name: string;
	vendor: string;
	/** `after_mean / before_mean`; null when the before mean is zero. */
	ratio: number | null;
	/** Null when the model appears in no exported snapshot shard. */
	selection: CompareSelection | null;
}

export interface UnstableFinding {
	cell: InstabilityCell;
	name: string;
	vendor: string;
	questionText: string;
	/** Null when the question has no kept snapshot days. */
	selection: CompareSelection | null;
}

/** Fewest adjacent-day pairs a cell needs before it can be ranked. */
export const MIN_CELL_PAIRS = 10;

function fingerprint(index: Index, modelId: string): { name: string; vendor: string } {
	const found = index.models.find((m) => m.model_id === modelId);
	return found
		? { name: found.name, vendor: found.vendor }
		: { name: modelId, vendor: modelId.split('/')[0] ?? '' };
}

/**
 * The kept snapshot days that bracket `day` for a question: the last kept day
 * strictly before it and the first kept day on or after it. When the event
 * falls outside the kept range the nearest end stands in, so the link always
 * opens two real snapshots.
 */
export function bracketDays(kept: readonly string[], day: string): [string, string] | null {
	if (kept.length === 0) return null;
	const sorted = [...kept].sort();
	const first = sorted[0] as string;
	const last = sorted[sorted.length - 1] as string;
	const before = sorted.filter((d) => d < day);
	const onOrAfter = sorted.filter((d) => d >= day);
	const dayA = before.length > 0 ? (before[before.length - 1] as string) : first;
	const dayB = onOrAfter.length > 0 ? (onOrAfter[0] as string) : last;
	return [dayA, dayB];
}

/**
 * The question on which a model is least stable, from the instability cells,
 * restricted to questions with kept snapshots so the compare page can show it.
 */
function questionFor(index: Index, modelId: string): string | null {
	const withSnapshots = index.cells
		.filter(
			(c) => c.model_id === modelId && (index.snapshot_days[c.question_slug]?.length ?? 0) > 0
		)
		.sort((a, b) => b.value - a.value);
	return withSnapshots[0]?.question_slug ?? null;
}

export function regimeChanges(index: Index, limit = 6): RegimeFinding[] {
	const ranked = [...index.changepoints].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
	return ranked.slice(0, limit).map((changepoint) => {
		const { name, vendor } = fingerprint(index, changepoint.model_id);
		const ratio =
			changepoint.before_mean > 0 ? changepoint.after_mean / changepoint.before_mean : null;
		const question = questionFor(index, changepoint.model_id);
		const bracket = question
			? bracketDays(index.snapshot_days[question] ?? [], changepoint.day)
			: null;
		const selection =
			question && bracket
				? { question, model: changepoint.model_id, dayA: bracket[0], dayB: bracket[1] }
				: null;
		return { changepoint, name, vendor, ratio, selection };
	});
}

export function unstablePairs(index: Index, limit = 6): UnstableFinding[] {
	const ranked = index.cells.filter((c) => c.n >= MIN_CELL_PAIRS).sort((a, b) => b.value - a.value);
	return ranked.slice(0, limit).map((cell) => {
		const { name, vendor } = fingerprint(index, cell.model_id);
		const kept = [...(index.snapshot_days[cell.question_slug] ?? [])].sort();
		const selection =
			kept.length > 0
				? {
						question: cell.question_slug,
						model: cell.model_id,
						dayA: kept[0] as string,
						dayB: kept[kept.length - 1] as string
					}
				: null;
		return {
			cell,
			name,
			vendor,
			questionText: index.questions[cell.question_slug]?.text ?? cell.question_slug,
			selection
		};
	});
}

/** The compare page's `#question|model|dayA|dayB` token for a selection. */
export function compareToken(selection: CompareSelection): string {
	return [selection.question, selection.model, selection.dayA, selection.dayB]
		.map(encodeURIComponent)
		.join('|');
}
