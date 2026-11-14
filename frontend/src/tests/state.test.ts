/**
 * The dataset state's method switching, with `fetch` stubbed.
 *
 * Switching measures swaps the whole index, so every chart re-renders under
 * the new distance; the shards are shared. This checks the state machine, not
 * the network: that the exported list drives the menu, that a switch is
 * memoised, and that a failed switch keeps the current measure on screen and
 * reports the failure rather than blanking the register.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function index(method: string, median: number): Record<string, unknown> {
	return {
		schema_version: 1,
		generated_at: '2026-10-22T00:00:00+00:00',
		method: { name: method, version: '1.0.0' },
		span: {
			first: '2026-07-18',
			last: '2026-10-22',
			days: 97,
			complete_days: 1,
			series_questions: 3,
			measured_questions: 3
		},
		noise: {
			n: 10,
			mean: median,
			median,
			p05: 0,
			p25: 0,
			p75: 0,
			p95: 0,
			p99: 0,
			std: 0,
			insufficient_data: false
		},
		timeline: [],
		decomposition: {
			stable: { mean: median, n: 10 },
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
		changepoints: []
	};
}

const manifest = {
	schema_version: 1,
	generated_at: '2026-10-22T00:00:00+00:00',
	git_sha: 'abc',
	antilethe_version: '0.1.0',
	methods_installed: [],
	methods_exported: ['cosine_bow', 'ncd', 'embedding'],
	ledger_head: null,
	row_count: 1,
	shard_bytes: {}
};

const routes: Record<string, unknown> = {
	'/data/index.json': index('cosine_bow', 0.158),
	'/data/manifest.json': manifest,
	'/data/methods/ncd.json': index('ncd', 0.41),
	'/data/methods/embedding.json': index('embedding', 0.03)
};

let fetched: string[] = [];

beforeEach(() => {
	fetched = [];
	vi.stubGlobal('fetch', async (url: string) => {
		fetched.push(url);
		const body = routes[url];
		if (body === undefined) return new Response('not here', { status: 404 });
		return new Response(JSON.stringify(body), {
			status: 200,
			headers: { 'content-type': 'application/json' }
		});
	});
	vi.resetModules();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

async function fresh() {
	const mod = await import('$lib/state/dataset.svelte');
	return mod.dataset;
}

describe('dataset method switching', () => {
	it('lists the exported measures with the loaded one first', async () => {
		const dataset = await fresh();
		await dataset.init();
		expect(dataset.method).toBe('cosine_bow');
		expect(dataset.methods).toEqual(['cosine_bow', 'ncd', 'embedding']);
		expect(dataset.index?.noise.median).toBe(0.158);
	});

	it('swaps the whole index on a switch and memoises it', async () => {
		const dataset = await fresh();
		await dataset.init();

		await dataset.selectMethod('ncd');
		expect(dataset.method).toBe('ncd');
		expect(dataset.index?.noise.median).toBe(0.41);
		expect(fetched.filter((u) => u.endsWith('/methods/ncd.json'))).toHaveLength(1);

		await dataset.selectMethod('cosine_bow');
		await dataset.selectMethod('ncd');
		// Both measures were cached after their first load.
		expect(fetched.filter((u) => u.endsWith('/methods/ncd.json'))).toHaveLength(1);
		expect(fetched.filter((u) => u.endsWith('/index.json'))).toHaveLength(1);
		expect(dataset.index?.method.name).toBe('ncd');
	});

	it('keeps the current measure on screen when a switch fails', async () => {
		const dataset = await fresh();
		await dataset.init();

		await dataset.selectMethod('nli');
		expect(dataset.method).toBe('cosine_bow');
		expect(dataset.index?.noise.median).toBe(0.158);
		expect(dataset.error).toMatch(/nli/);
		expect(dataset.switching).toBe(false);
	});

	it('includes a loaded measure the manifest does not list', async () => {
		routes['/data/manifest.json'] = { ...manifest, methods_exported: ['ncd'] };
		const dataset = await fresh();
		await dataset.init();
		expect(dataset.methods).toEqual(['cosine_bow', 'ncd']);
		routes['/data/manifest.json'] = manifest;
	});
});
