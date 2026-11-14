/**
 * Word-level diff, mirroring `backend/src/antilethe/diffing.py`.
 *
 * The static site has no backend, so the compare view diffs in the browser.
 * The algorithm is the same longest-common-subsequence walk the Python side
 * uses, and `src/tests/diff.test.ts` checks the properties both must satisfy.
 */

import type { DiffToken } from './types';

/** Split text into whitespace-preserving word tokens. */
export function tokenize(text: string): string[] {
	return text.match(/\S+\s*/g) ?? [];
}

/**
 * Longest common subsequence table over two token arrays.
 *
 * Quadratic in the token counts. Snapshots are capped at 4000 characters by the
 * exporter, so the worst case is a few hundred thousand cells, which is
 * comfortably fast and avoids pulling in a diff dependency.
 */
function lcsLengths(a: string[], b: string[]): Uint32Array[] {
	const rows: Uint32Array[] = [];
	for (let i = 0; i <= a.length; i += 1) rows.push(new Uint32Array(b.length + 1));
	for (let i = a.length - 1; i >= 0; i -= 1) {
		for (let j = b.length - 1; j >= 0; j -= 1) {
			rows[i][j] =
				a[i] === b[j] ? rows[i + 1][j + 1] + 1 : Math.max(rows[i + 1][j], rows[i][j + 1]);
		}
	}
	return rows;
}

/** Diff two texts at word granularity, merging adjacent runs. */
export function wordDiff(before: string, after: string): DiffToken[] {
	const a = tokenize(before);
	const b = tokenize(after);
	const out: DiffToken[] = [];

	function push(op: DiffToken['op'], text: string): void {
		if (!text) return;
		const last = out[out.length - 1];
		if (last && last.op === op) last.text += text;
		else out.push({ op, text });
	}

	if (a.length === 0 && b.length === 0) return out;
	if (a.length === 0) {
		push('insert', b.join(''));
		return out;
	}
	if (b.length === 0) {
		push('delete', a.join(''));
		return out;
	}

	const table = lcsLengths(a, b);
	let i = 0;
	let j = 0;
	while (i < a.length && j < b.length) {
		if (a[i] === b[j]) {
			push('equal', a[i]);
			i += 1;
			j += 1;
		} else if (table[i + 1][j] >= table[i][j + 1]) {
			push('delete', a[i]);
			i += 1;
		} else {
			push('insert', b[j]);
			j += 1;
		}
	}
	if (i < a.length) push('delete', a.slice(i).join(''));
	if (j < b.length) push('insert', b.slice(j).join(''));
	return out;
}

/** How many words changed, as a fraction of the longer text. */
export function changeFraction(tokens: DiffToken[]): number {
	let changed = 0;
	let total = 0;
	for (const token of tokens) {
		const words = tokenize(token.text).length;
		total += words;
		if (token.op !== 'equal') changed += words;
	}
	return total === 0 ? 0 : changed / total;
}
