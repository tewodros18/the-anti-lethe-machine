/**
 * The home page's headline findings are pure functions of the index.
 *
 * Ranking is by magnitude, cells with too few pairs never rank, and every
 * finding's compare-page selection points at two kept snapshot days that
 * bracket the event, so a reader clicking a claim lands on its evidence.
 */

import { describe, expect, it } from 'vitest';

import {
	MIN_CELL_PAIRS,
	bracketDays,
	compareToken,
	regimeChanges,
	unstablePairs
} from '../lib/data/findings';
import type { Changepoint, Index } from '../lib/data/types';

const KEPT = ['2026-07-18', '2026-07-25', '2026-08-01', '2026-08-08'];

function index(): Index {
	return {
		models: [
			{ model_id: 'a/one', name: 'One', vendor: 'a' },
			{ model_id: 'b/two', name: 'Two', vendor: 'b' }
		],
		questions: { q1: { text: 'Question one?', tags: [] }, q2: { text: 'Question two?', tags: [] } },
		snapshot_days: { q1: KEPT, q2: [] },
		cells: [
			{ question_slug: 'q1', model_id: 'a/one', value: 0.2, n: 40 },
			{ question_slug: 'q2', model_id: 'a/one', value: 0.9, n: 40 },
			{ question_slug: 'q1', model_id: 'b/two', value: 0.5, n: 3 }
		],
		changepoints: [
			{
				model_id: 'a/one',
				day: '2026-07-30',
				before_mean: 0.05,
				after_mean: 0.1,
				delta: 0.05,
				n_before: 5,
				n_after: 20,
				coincides_with: null
			},
			{
				model_id: 'b/two',
				day: '2026-08-02',
				before_mean: 0.1,
				after_mean: 0.02,
				delta: -0.08,
				n_before: 8,
				n_after: 30,
				coincides_with: 'provider'
			}
		]
	} as unknown as Index;
}

describe('bracketDays', () => {
	it('picks the last kept day before and the first on or after the event', () => {
		expect(bracketDays(KEPT, '2026-07-30')).toEqual(['2026-07-25', '2026-08-01']);
	});
	it('falls back to the ends of the kept range', () => {
		expect(bracketDays(KEPT, '2026-07-01')).toEqual(['2026-07-18', '2026-07-18']);
		expect(bracketDays(KEPT, '2026-09-01')).toEqual(['2026-08-08', '2026-08-08']);
		expect(bracketDays([], '2026-08-01')).toBeNull();
	});
});

describe('regimeChanges', () => {
	it('ranks by the magnitude of the break and names the recorded cause', () => {
		const found = regimeChanges(index());
		expect(found.map((f) => f.changepoint.model_id)).toEqual(['b/two', 'a/one']);
		expect(found[0]?.changepoint.coincides_with).toBe('provider');
		expect(found[0]?.ratio).toBeCloseTo(0.2);
	});
	it('links each break to the least stable question that has snapshots', () => {
		const [, one] = regimeChanges(index());
		// q2 is less stable for a/one but has no kept days, so q1 is chosen.
		expect(one?.selection).toEqual({
			question: 'q1',
			model: 'a/one',
			dayA: '2026-07-25',
			dayB: '2026-08-01'
		});
	});
	it('reports no ratio when the before mean is zero', () => {
		const idx = index();
		const first = idx.changepoints[0] as Changepoint;
		idx.changepoints[0] = { ...first, before_mean: 0 };
		const [, one] = regimeChanges(idx);
		expect(one?.ratio).toBeNull();
	});
});

describe('unstablePairs', () => {
	it('excludes cells with too few pairs and ranks the rest by distance', () => {
		const found = unstablePairs(index());
		expect(found.every((f) => f.cell.n >= MIN_CELL_PAIRS)).toBe(true);
		expect(found.map((f) => f.cell.question_slug)).toEqual(['q2', 'q1']);
		expect(found[0]?.selection).toBeNull();
		expect(found[1]?.selection).toEqual({
			question: 'q1',
			model: 'a/one',
			dayA: '2026-07-18',
			dayB: '2026-08-08'
		});
	});
});

describe('compareToken', () => {
	it('matches the compare page hash, pipe-separated and URI-encoded', () => {
		expect(
			compareToken({ question: 'q 1', model: 'a/one', dayA: '2026-07-18', dayB: '2026-08-08' })
		).toBe('q%201|a%2Fone|2026-07-18|2026-08-08');
	});
});
