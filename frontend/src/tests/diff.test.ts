import { describe, expect, it } from 'vitest';
import { changeFraction, tokenize, wordDiff } from '$lib/data/diff';

/** Reassemble what each side of the diff claims the original text was. */
function rebuild(tokens: ReturnType<typeof wordDiff>, side: 'before' | 'after'): string {
	return tokens
		.filter((t) => t.op === 'equal' || (side === 'before' ? t.op === 'delete' : t.op === 'insert'))
		.map((t) => t.text)
		.join('');
}

describe('tokenize', () => {
	it('keeps trailing whitespace with each token', () => {
		expect(tokenize('a b  c')).toEqual(['a ', 'b  ', 'c']);
	});

	it('handles an empty string', () => {
		expect(tokenize('')).toEqual([]);
	});

	it('round-trips exactly', () => {
		const text = 'Coffee is  broadly safe.\nEven so, moderation helps.';
		expect(tokenize(text).join('')).toBe(text);
	});
});

describe('wordDiff', () => {
	it('reports identical text as one equal run', () => {
		const tokens = wordDiff('the same text', 'the same text');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].op).toBe('equal');
	});

	it('reconstructs both sides losslessly', () => {
		const before = 'Coffee appears broadly safe for most adults in moderate amounts.';
		const after = 'Coffee is broadly safe for the majority of adults in moderation.';
		const tokens = wordDiff(before, after);
		expect(rebuild(tokens, 'before')).toBe(before);
		expect(rebuild(tokens, 'after')).toBe(after);
	});

	it('reconstructs losslessly across a range of edits', () => {
		const cases: [string, string][] = [
			['', ''],
			['', 'all new text here'],
			['all old text here', ''],
			['a b c d e', 'a c e'],
			['a c e', 'a b c d e'],
			['one two three', 'three two one'],
			['repeat repeat repeat', 'repeat'],
			['x', 'y'],
			['the quick brown fox', 'the slow brown dog']
		];
		for (const [before, after] of cases) {
			const tokens = wordDiff(before, after);
			expect(rebuild(tokens, 'before'), `before: ${before}`).toBe(before);
			expect(rebuild(tokens, 'after'), `after: ${after}`).toBe(after);
		}
	});

	it('marks an insertion into empty text', () => {
		const tokens = wordDiff('', 'brand new');
		expect(tokens).toEqual([{ op: 'insert', text: 'brand new' }]);
	});

	it('marks a deletion to empty text', () => {
		const tokens = wordDiff('was here', '');
		expect(tokens).toEqual([{ op: 'delete', text: 'was here' }]);
	});

	it('merges adjacent runs of the same operation', () => {
		const tokens = wordDiff('a b c', 'a x y z c');
		for (let i = 1; i < tokens.length; i += 1) {
			expect(tokens[i].op).not.toBe(tokens[i - 1].op);
		}
	});

	it('detects a negation as a change', () => {
		const tokens = wordDiff('coffee is safe', 'coffee is not safe');
		expect(tokens.some((t) => t.op === 'insert')).toBe(true);
	});

	it('finds the common subsequence rather than replacing wholesale', () => {
		const tokens = wordDiff('alpha beta gamma', 'alpha delta gamma');
		const equal = tokens.filter((t) => t.op === 'equal');
		expect(equal.length).toBeGreaterThan(0);
		expect(equal.map((t) => t.text).join('')).toContain('alpha');
	});

	it('handles realistic snapshot lengths', () => {
		const before = Array.from({ length: 600 }, (_, i) => `word${i}`).join(' ');
		const after = Array.from({ length: 600 }, (_, i) =>
			i % 50 === 0 ? `changed${i}` : `word${i}`
		).join(' ');
		const tokens = wordDiff(before, after);
		expect(rebuild(tokens, 'before')).toBe(before);
		expect(rebuild(tokens, 'after')).toBe(after);
	});
});

describe('changeFraction', () => {
	it('is zero for identical text', () => {
		expect(changeFraction(wordDiff('same words here', 'same words here'))).toBe(0);
	});

	it('is one when nothing is shared', () => {
		expect(changeFraction(wordDiff('alpha', 'beta'))).toBe(1);
	});

	it('is zero for two empty texts', () => {
		expect(changeFraction(wordDiff('', ''))).toBe(0);
	});

	it('is between zero and one otherwise', () => {
		const fraction = changeFraction(wordDiff('a b c d', 'a b x d'));
		expect(fraction).toBeGreaterThan(0);
		expect(fraction).toBeLessThan(1);
	});
});
