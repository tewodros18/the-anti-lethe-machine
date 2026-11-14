import { describe, expect, it } from 'vitest';
import { DatasetError, validateIndex, validateManifest, validateShard } from '$lib/data/load';

/** A minimal index with every key the validator insists on. */
function minimalIndex(overrides: Record<string, unknown> = {}): Record<string, unknown> {
	return {
		schema_version: 1,
		generated_at: '2026-03-04T00:00:00+00:00',
		method: { name: 'cosine_bow', version: '1.0.0' },
		span: {
			first: '2026-03-01',
			last: '2026-03-04',
			days: 4,
			complete_days: 4,
			series_questions: 2,
			measured_questions: 2
		},
		noise: {
			n: 12,
			mean: 0.1,
			median: 0.09,
			p05: 0.01,
			p25: 0.05,
			p75: 0.14,
			p95: 0.2,
			p99: 0.3,
			std: 0.05,
			insufficient_data: false
		},
		timeline: [],
		decomposition: {
			stable: { mean: 0.1, n: 12 },
			provider: { mean: null, n: 0 },
			version: { mean: null, n: 0 },
			provider_ratio: null,
			version_ratio: null,
			provider_ratio_ci: null,
			version_ratio_ci: null,
			provider_within: null,
			version_within: null
		},
		models: [],
		questions: {},
		cells: [],
		version_events: [],
		provider_events: [],
		price_changes: [],
		gaps: { adjacent: 6, multi_day: 0, max_days: 1, models_with_gaps: 0 },
		snapshot_days: {},
		changepoints: [],
		...overrides
	};
}

describe('validateIndex', () => {
	it('accepts a well-formed index', () => {
		const index = validateIndex(minimalIndex());
		expect(index.method.name).toBe('cosine_bow');
	});

	it('preserves nulls rather than coercing them', () => {
		const index = validateIndex(minimalIndex());
		expect(index.decomposition.provider_ratio).toBeNull();
		expect(index.decomposition.version.mean).toBeNull();
	});

	it('rejects a non-object payload', () => {
		expect(() => validateIndex([])).toThrow(DatasetError);
		expect(() => validateIndex(null)).toThrow(DatasetError);
		expect(() => validateIndex('nope')).toThrow(DatasetError);
	});

	it('rejects an unknown schema version with an actionable message', () => {
		expect(() => validateIndex(minimalIndex({ schema_version: 2 }))).toThrow(/version 1/);
	});

	it('names the missing key', () => {
		const payload = minimalIndex();
		delete payload.noise;
		expect(() => validateIndex(payload)).toThrow(/noise/);
	});

	it('rejects a non-array where an array belongs', () => {
		expect(() => validateIndex(minimalIndex({ models: {} }))).toThrow(/models/);
		expect(() => validateIndex(minimalIndex({ timeline: 'no' }))).toThrow(/timeline/);
	});
});

describe('validateManifest', () => {
	it('accepts a well-formed manifest', () => {
		const manifest = validateManifest({
			schema_version: 1,
			generated_at: '2026-03-04T00:00:00+00:00',
			git_sha: 'abc123',
			antilethe_version: '0.1.0',
			methods_installed: [{ name: 'cosine_bow', kind: 'pairwise', version: '1.0.0', model: null }],
			methods_exported: ['cosine_bow'],
			ledger_head: { day: '2026-03-04', merkle_root: 'ff'.repeat(32) },
			row_count: 17,
			shard_bytes: {}
		});
		expect(manifest.methods_installed).toHaveLength(1);
	});

	it('allows a null ledger head', () => {
		const manifest = validateManifest({
			schema_version: 1,
			generated_at: '2026-03-04T00:00:00+00:00',
			git_sha: 'abc123',
			antilethe_version: '0.1.0',
			methods_installed: [],
			methods_exported: [],
			ledger_head: null,
			row_count: 0,
			shard_bytes: {}
		});
		expect(manifest.ledger_head).toBeNull();
	});

	it('rejects a bad schema version', () => {
		expect(() => validateManifest({ schema_version: 9, methods_installed: [] })).toThrow(
			DatasetError
		);
	});
});

describe('validateShard', () => {
	it('accepts a well-formed shard', () => {
		const shard = validateShard(
			{
				question_slug: 'is-coffee-good-for-you',
				question_text: 'Is coffee good for you?',
				models: {
					'openweight/steady-7b': {
						'2026-03-01': {
							text: 'Coffee is broadly safe.',
							truncated: false,
							sha256: 'ab'.repeat(32),
							canonical_slug: 'openweight/steady-7b',
							serving_host: 'Novita',
							duration_ms: 1800,
							word_count: 4,
							refusal: false
						}
					}
				}
			},
			'is-coffee-good-for-you'
		);
		expect(Object.keys(shard.models)).toHaveLength(1);
	});

	it('names the shard in its error', () => {
		expect(() => validateShard({ models: {} }, 'some-slug')).toThrow(/some-slug/);
	});

	it('rejects a shard whose models is not an object', () => {
		expect(() => validateShard({ question_slug: 'x', models: [] }, 'x')).toThrow(DatasetError);
	});
});
