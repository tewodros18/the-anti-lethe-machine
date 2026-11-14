/**
 * Component rendering tests, focused on one thing: a null in the dataset must
 * reach the screen as an em dash and never as a zero.
 *
 * That rule is the whole point of the project, it lives in the components rather
 * than in the pipeline, and it is the one thing a type checker cannot verify.
 * These tests also exercise the "Show as table" fallback, which is the
 * accessible path to every chart's numbers and renders them without needing
 * layout, so it works under a headless DOM.
 */

import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import Decomposition from '$lib/charts/Decomposition.svelte';
import Heatmap from '$lib/charts/Heatmap.svelte';
import Radar from '$lib/charts/Radar.svelte';
import DriftTimeline from '$lib/charts/DriftTimeline.svelte';
import DataTable from '$lib/components/DataTable.svelte';
import ReadingStrip from '$lib/components/ReadingStrip.svelte';
import { EM_DASH } from '$lib/data/format';
import type {
	Decomposition as Decomp,
	ModelFingerprint,
	NoiseStats,
	TimelinePoint
} from '$lib/data/types';

afterEach(cleanup);

const noise: NoiseStats = {
	n: 1138,
	mean: 0.191947,
	median: 0.172187,
	p05: 0.084625,
	p25: 0.12,
	p75: 0.25,
	p95: 0.366762,
	p99: 0.5,
	std: 0.09,
	insufficient_data: false
};

const timeline: TimelinePoint[] = [
	{
		day: '2026-10-01',
		stable: 0.1721,
		provider: 0.2555,
		version: null,
		n_stable: 20,
		n_provider: 3,
		n_version: 0
	},
	{
		day: '2026-10-02',
		stable: 0.1805,
		provider: null,
		version: null,
		n_stable: 21,
		n_provider: 0,
		n_version: 0
	}
];

/** The real shape of the live archive: no repoint was observed in the window. */
const noRebuilds: Decomp = {
	stable: { mean: 0.191947, n: 1138 },
	provider: { mean: 0.255565, n: 191 },
	version: { mean: null, n: 0 },
	provider_ratio: 1.331435,
	version_ratio: null,
	provider_ratio_ci: null,
	version_ratio_ci: null,
	provider_within: null,
	version_within: null
};

function fingerprint(over: Partial<ModelFingerprint> = {}): ModelFingerprint {
	return {
		model_id: 'deepseek/deepseek-chat',
		name: 'DeepSeek: Chat',
		vendor: 'deepseek',
		n_answers: 73,
		mean_words: 420,
		refusal_rate: 0,
		hedge_rate: 2.1,
		reasoning_frac: 0,
		mean_duration_ms: 18000,
		mean_cost: 0.0004,
		d_stable: 0.2168,
		d_provider: 0.2687,
		d_version: null,
		noise,
		repoints: 0,
		host_switches: 33,
		hosts_seen: ['DeepInfra', 'Novita', 'StreamLake'],
		daily: [0.21, null],
		...over
	};
}

describe('Decomposition', () => {
	it('renders an em dash, not a zero, for an unobserved stratum', () => {
		render(Decomposition, { decomposition: noRebuilds });

		// The host effect is measured and shown as a ratio.
		expect(screen.getByText('1.33×')).toBeTruthy();

		// The rebuild effect is not measurable and must read as an em dash.
		const rebuild = screen.getByText('rebuild effect').parentElement;
		expect(rebuild?.textContent).toContain(EM_DASH);
		expect(rebuild?.textContent).not.toContain('0.00');
	});

	it('says in words that no rebuild was observed', () => {
		render(Decomposition, { decomposition: noRebuilds });
		const body = document.body.textContent ?? '';
		expect(body).toMatch(/No model rebuilds occurred in this window/i);
		// And states the host-effect finding with its sample size.
		expect(body).toMatch(/1\.33×/);
		expect(body).toMatch(/191/);
	});

	it('refuses to compute a ratio with no noise floor', () => {
		render(Decomposition, {
			decomposition: {
				stable: { mean: null, n: 2 },
				provider: { mean: 0.3, n: 5 },
				version: { mean: null, n: 0 },
				provider_ratio: null,
				version_ratio: null,
				provider_ratio_ci: null,
				version_ratio_ci: null,
				provider_within: null,
				version_within: null
			}
		});
		expect(document.body.textContent).toMatch(
			/not yet enough .* pairs to establish a noise floor/i
		);
	});

	it('shows the same numbers in the table fallback', async () => {
		const { getByText } = render(Decomposition, { decomposition: noRebuilds });
		(getByText('Show as table') as HTMLButtonElement).click();
		await Promise.resolve();

		const table = document.querySelector('table');
		expect(table).toBeTruthy();
		const text = table?.textContent ?? '';
		expect(text).toContain('0.192'); // stable mean
		expect(text).toContain('0.256'); // provider mean
		expect(text).toContain(EM_DASH); // version mean is null
		expect(text).toContain('baseline');
	});
});

describe('DriftTimeline', () => {
	it('mounts and exposes a table of the same values', async () => {
		const { getByText } = render(DriftTimeline, {
			timeline,
			noise,
			versionEvents: [],
			providerEvents: [
				{
					day: '2026-10-01',
					model_id: 'deepseek/deepseek-chat',
					from_host: 'Novita',
					to_host: 'DeepInfra'
				}
			]
		});

		(getByText('Show as table') as HTMLButtonElement).click();
		await Promise.resolve();

		const text = document.querySelector('table')?.textContent ?? '';
		expect(text).toContain('2026-10-01');
		expect(text).toContain('0.172');
		// A day with no pairs in a stratum shows an em dash, not 0.000.
		expect(text).toContain(EM_DASH);
	});

	it('labels the legend with the stratum meanings, not raw field names', () => {
		render(DriftTimeline, {
			timeline,
			noise,
			versionEvents: [],
			providerEvents: []
		});
		const body = document.body.textContent ?? '';
		expect(body).toContain('Same build, same host');
		expect(body).toMatch(/Host switch/);
		expect(body).toMatch(/Model rebuild/);
	});
});

describe('DataTable', () => {
	it('badges the host effect and em-dashes an unmeasurable one', () => {
		render(DataTable, {
			models: [
				fingerprint(),
				fingerprint({
					model_id: 'openai/gpt-5',
					name: 'OpenAI: GPT-5',
					vendor: 'openai',
					d_provider: null, // never served by a second host
					host_switches: 0,
					hosts_seen: ['OpenAI']
				})
			]
		});

		// 0.2687 / 0.2168 = 1.24
		expect(screen.getByText('1.24×')).toBeTruthy();

		const row = screen.getByText('OpenAI: GPT-5').closest('tr');
		expect(row?.textContent).toContain(EM_DASH);
	});

	it('sorts nulls last regardless of direction', async () => {
		const { getByTitle } = render(DataTable, {
			models: [
				fingerprint({ model_id: 'a/one', name: 'One', d_provider: null }),
				fingerprint({ model_id: 'b/two', name: 'Two', d_stable: 0.1, d_provider: 0.5 })
			]
		});

		const header = getByTitle('Host-switch distance ÷ noise') as HTMLButtonElement;
		const names = () =>
			[...document.querySelectorAll('tbody tr th')].map((el) => el.textContent?.trim() ?? '');

		expect(names()[names().length - 1]).toContain('One');
		header.click();
		await Promise.resolve();
		expect(names()[names().length - 1]).toContain('One');
	});
});

describe('ReadingStrip', () => {
	it('marks an em dash reading as absent rather than zero', () => {
		render(ReadingStrip, {
			readings: [
				{ label: 'Host effect', value: '1.33×' },
				{ label: 'Rebuild effect', value: EM_DASH, note: 'none observed' }
			]
		});
		const dd = screen.getByText(EM_DASH);
		expect(dd.classList.contains('nil')).toBe(true);
		expect(document.body.textContent).toContain('none observed');
	});
});

describe('Radar', () => {
	it('mounts the polar layers and scales each axis across the shown models', async () => {
		const { getByText } = render(Radar, {
			models: [
				fingerprint(),
				fingerprint({
					model_id: 'openai/gpt-5',
					name: 'OpenAI: GPT-5',
					vendor: 'openai',
					mean_words: 900,
					hedge_rate: 0.8,
					mean_duration_ms: 42000,
					d_stable: 0.11
				})
			]
		});

		// Both models are named in the legend and again as each polygon's
		// accessible title, so the name appears more than once by design.
		expect(screen.getAllByText('DeepSeek: Chat').length).toBeGreaterThan(0);
		expect(screen.getAllByText('OpenAI: GPT-5').length).toBeGreaterThan(0);
		// One polygon per selected model actually rendered.
		expect(document.querySelectorAll('.radar-area').length).toBe(2);
		// And the polar grid drew a spoke per axis.
		expect(document.querySelectorAll('.web .axis-label').length).toBe(6);

		// The accessible description states that the scaling is relative.
		const desc = document.querySelector('#radar-desc')?.textContent ?? '';
		expect(desc).toMatch(/scaled between the lowest and highest value/i);

		// The table fallback shows the raw values, with the inversion labelled.
		(getByText('Show as table') as HTMLButtonElement).click();
		await Promise.resolve();
		const table = document.querySelector('table')?.textContent ?? '';
		expect(table).toMatch(/lower is further out/);
		expect(table).toContain('900'); // raw verbosity, not a 0-1 scaled value
	});
});

describe('Heatmap', () => {
	it('mounts cells and states what the opacity means', async () => {
		const { getByText } = render(Heatmap, {
			cells: [
				{ question_slug: 'q-one', model_id: 'a/one', value: 0.31, n: 70 },
				{ question_slug: 'q-two', model_id: 'a/one', value: 0.07, n: 70 }
			],
			questions: {
				'q-one': { text: 'A question that moves a lot', tags: [] },
				'q-two': { text: 'A settled question', tags: [] }
			}
		});

		expect(document.body.textContent).toMatch(/Darker means/i);

		(getByText('Show as table') as HTMLButtonElement).click();
		await Promise.resolve();
		const table = document.querySelector('table')?.textContent ?? '';
		expect(table).toContain('A question that moves a lot');
		expect(table).toContain('0.310');
		expect(table).toContain('0.070');
	});
});

describe('Decomposition, within-model', () => {
	it('leads with the within-model median and keeps the pooled ratio as context', () => {
		render(Decomposition, {
			decomposition: {
				...noRebuilds,
				provider_ratio: 0.903,
				provider_ratio_ci: [0.86, 0.95],
				provider_within: { median: 1.049, q25: 0.962, q75: 1.224, n: 17, above_one: 12 }
			}
		});
		const body = document.body.textContent ?? '';
		expect(body).toMatch(/Within a model, .* a median 1\.05×/);
		expect(body).toMatch(/12 of 17 models above 1×/);
		expect(body).toMatch(/Pooled over all 191 host-switch pairs the ratio is 0\.90×/);
		expect(screen.getByText('host effect, within model')).toBeTruthy();
		expect(screen.getByText('host effect, pooled')).toBeTruthy();
	});
});
