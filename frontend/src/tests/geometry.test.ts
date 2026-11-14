/**
 * Chart geometry, asserted in pixels.
 *
 * The render tests prove the charts mount and that nulls reach the screen as
 * em dashes. They cannot prove a vertex is where it should be, because a
 * headless DOM reports every element as 0×0 and LayerCake sizes its scales from
 * the container. This file gives every element a fixed 600×400 box and a
 * ResizeObserver that reports it at once, then checks the coordinates the
 * layers actually emit against the arithmetic LayerCake is supposed to do.
 *
 * Kept in its own file: the fake observer must be installed before Svelte's
 * lazy observer singleton is first created, and vitest isolates files.
 */

import { cleanup, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';

import Decomposition from '$lib/charts/Decomposition.svelte';
import DriftTimeline from '$lib/charts/DriftTimeline.svelte';
import Heatmap from '$lib/charts/Heatmap.svelte';
import Radar from '$lib/charts/Radar.svelte';
import type { ModelFingerprint, NoiseStats } from '$lib/data/types';

const WIDTH = 600;
const HEIGHT = 400;
const FLOOR = 0.12;

beforeAll(() => {
	// Every element measures 600×400. happy-dom defines these getters on
	// HTMLElement.prototype, which would shadow a stub on Element.prototype,
	// so both are overridden.
	for (const proto of [Element.prototype, HTMLElement.prototype]) {
		for (const name of ['clientWidth', 'offsetWidth'] as const) {
			Object.defineProperty(proto, name, { configurable: true, get: () => WIDTH });
		}
		for (const name of ['clientHeight', 'offsetHeight'] as const) {
			Object.defineProperty(proto, name, { configurable: true, get: () => HEIGHT });
		}
	}
	// Svelte's size bindings read the element after a ResizeObserver callback.
	// This observer reports immediately, on a microtask, as a real one would
	// after layout.
	class ImmediateResizeObserver {
		#callback: ResizeObserverCallback;
		constructor(callback: ResizeObserverCallback) {
			this.#callback = callback;
		}
		observe(target: Element): void {
			queueMicrotask(() =>
				this.#callback(
					[
						{
							target,
							contentRect: { width: WIDTH, height: HEIGHT } as DOMRectReadOnly
						} as ResizeObserverEntry
					],
					this as unknown as ResizeObserver
				)
			);
		}
		unobserve(): void {}
		disconnect(): void {}
	}
	Object.defineProperty(globalThis, 'ResizeObserver', {
		configurable: true,
		value: ImmediateResizeObserver
	});
});

afterEach(cleanup);

/** Let the observer fire and the derived scales settle. */
async function settle(): Promise<void> {
	await new Promise((resolve) => setTimeout(resolve, 0));
	await tick();
	await new Promise((resolve) => setTimeout(resolve, 0));
	await tick();
}

/** Parse the numeric coordinate pairs out of an SVG path or points string. */
function pairs(d: string): [number, number][] {
	return [...d.matchAll(/(-?[\d.]+(?:e-?\d+)?),(-?[\d.]+(?:e-?\d+)?)/g)].map((m) => [
		Number(m[1]),
		Number(m[2])
	]);
}

function translate(el: Element | null): [number, number] {
	const m = /translate\(([-\d.]+),([-\d.]+)\)/.exec(el?.getAttribute('transform') ?? '');
	return m ? [Number(m[1]), Number(m[2])] : [NaN, NaN];
}

const noise: NoiseStats = {
	n: 100,
	mean: 0.2,
	median: 0.2,
	p05: 0.1,
	p25: 0.15,
	p75: 0.25,
	p95: 0.3,
	p99: 0.35,
	std: 0.05,
	insufficient_data: false
};

function fingerprint(over: Partial<ModelFingerprint>): ModelFingerprint {
	return {
		model_id: 'v/m',
		name: 'M',
		vendor: 'v',
		n_answers: 10,
		mean_words: 100,
		refusal_rate: 0,
		hedge_rate: 1,
		reasoning_frac: 0,
		mean_duration_ms: 1000,
		mean_cost: 0,
		d_stable: 0.1,
		d_provider: null,
		d_version: null,
		noise,
		repoints: 0,
		host_switches: 0,
		hosts_seen: [],
		daily: [],
		...over
	};
}

describe('Radar geometry', () => {
	// padding 30/84/30/84 on 600×400 -> plot 432×340 -> outer radius 170.
	const OUTER = Math.min(WIDTH - 168, HEIGHT - 60) / 2;

	// `best` is max on every non-inverted axis and min on both inverted ones,
	// so after orientation it is 1.0 everywhere; `worst` is the opposite.
	const best = fingerprint({
		model_id: 'a/best',
		name: 'Best',
		d_stable: 0.1,
		mean_words: 500,
		hedge_rate: 3,
		refusal_rate: 0.2,
		reasoning_frac: 0.5,
		mean_duration_ms: 1000
	});
	const worst = fingerprint({
		model_id: 'b/worst',
		name: 'Worst',
		d_stable: 0.3,
		mean_words: 100,
		hedge_rate: 1,
		refusal_rate: 0,
		reasoning_frac: 0,
		mean_duration_ms: 5000
	});

	it('centres the web and the shapes on the plot', async () => {
		render(Radar, { models: [best, worst] });
		await settle();
		expect(translate(document.querySelector('.web'))).toEqual([216, 170]);
		expect(translate(document.querySelector('.radar-area'))).toEqual([216, 170]);
	});

	it('puts the best model on the rim and the worst on the floor ring, never the centre', async () => {
		render(Radar, { models: [best, worst] });
		await settle();
		const outlines = document.querySelectorAll('.radar-area path.outline');
		expect(outlines).toHaveLength(2);

		const bestPts = pairs(outlines[0].getAttribute('d') ?? '');
		const worstPts = pairs(outlines[1].getAttribute('d') ?? '');
		expect(bestPts).toHaveLength(6);
		expect(worstPts).toHaveLength(6);

		for (const [x, y] of bestPts) expect(Math.hypot(x, y)).toBeCloseTo(OUTER, 1);
		for (const [x, y] of worstPts) expect(Math.hypot(x, y)).toBeCloseTo(FLOOR * OUTER, 1);
		// The worst model is not at the origin: that would read as zero.
		for (const [x, y] of worstPts) expect(Math.hypot(x, y)).toBeGreaterThan(10);
	});

	it('starts at twelve o’clock and goes clockwise, matching the web’s spokes', async () => {
		render(Radar, { models: [best, worst] });
		await settle();
		const bestPts = pairs(
			document.querySelector('.radar-area path.outline')?.getAttribute('d') ?? ''
		);
		// First axis straight up.
		expect(bestPts[0][0]).toBeCloseTo(0, 5);
		expect(bestPts[0][1]).toBeCloseTo(-OUTER, 5);
		// Second axis 60° clockwise: x positive, y negative.
		expect(bestPts[1][0]).toBeCloseTo(OUTER * Math.cos(-Math.PI / 6), 5);
		expect(bestPts[1][1]).toBeCloseTo(OUTER * Math.sin(-Math.PI / 6), 5);

		const spokes = document.querySelectorAll('.web line.spoke');
		expect(spokes).toHaveLength(6);
		expect(Number(spokes[0].getAttribute('x2'))).toBeCloseTo(0, 5);
		expect(Number(spokes[0].getAttribute('y2'))).toBeCloseTo(-OUTER, 5);
	});

	it('draws the rim ring at the outer radius and the innermost ring at the floor', async () => {
		render(Radar, { models: [best, worst] });
		await settle();
		const rings = [...document.querySelectorAll('.web polygon.ring')];
		expect(rings).toHaveLength(4);
		const radii = rings.map((r) => {
			const [x, y] = pairs(r.getAttribute('points') ?? '')[0];
			return Math.hypot(x, y);
		});
		expect(Math.min(...radii)).toBeCloseTo(FLOOR * OUTER, 1);
		expect(Math.max(...radii)).toBeCloseTo(OUTER, 1);
	});

	it('draws a flat axis at mid-radius, mutes its label, and says so', async () => {
		// Both models identical on refusal and reasoning.
		render(Radar, {
			models: [best, fingerprint({ ...worst, refusal_rate: 0.2, reasoning_frac: 0.5 })]
		});
		await settle();
		const pts = pairs(document.querySelector('.radar-area path.outline')?.getAttribute('d') ?? '');
		// Axis index 3 = refusal, 4 = reasoning.
		expect(Math.hypot(...pts[3])).toBeCloseTo(0.5 * OUTER, 1);
		expect(Math.hypot(...pts[4])).toBeCloseTo(0.5 * OUTER, 1);

		const muted = [...document.querySelectorAll('.web text.axis-label.muted')].map(
			(t) => t.textContent
		);
		expect(muted).toEqual(['Refusal', 'Reasoning']);
		expect(document.body.textContent).toMatch(/No variation .* Refusal, Reasoning/);
	});

	it('breaks the outline at a null axis instead of spiking to the centre', async () => {
		render(Radar, { models: [best, fingerprint({ ...worst, d_stable: null })] });
		await settle();
		const outlines = document.querySelectorAll('.radar-area path.outline');
		const d = outlines[1].getAttribute('d') ?? '';
		// Open path: no Z, exactly one sub-path, five vertices, no fill.
		expect(d).not.toContain('Z');
		expect(d.split('M').length - 1).toBe(1);
		expect(pairs(d)).toHaveLength(5);
		expect(outlines[1].getAttribute('fill')).toBe('none');
		for (const [x, y] of pairs(d)) expect(Math.hypot(x, y)).toBeGreaterThan(10);
		// Still five vertex dots, not six.
		expect(outlines[1].parentElement?.querySelectorAll('circle')).toHaveLength(5);
	});
});

describe('DriftTimeline geometry', () => {
	// padding 16/20/40/56 on 600×400 -> plot 524×344.
	const PLOT_H = HEIGHT - 56;

	it('scales the noise band and median rule from the same y scale as the line', async () => {
		render(DriftTimeline, {
			timeline: [
				{
					day: '2026-10-01',
					stable: 0.2,
					provider: null,
					version: null,
					n_stable: 5,
					n_provider: 0,
					n_version: 0
				},
				{
					day: '2026-10-02',
					stable: 0.2,
					provider: null,
					version: null,
					n_stable: 5,
					n_provider: 0,
					n_version: 0
				}
			],
			noise,
			versionEvents: [],
			providerEvents: []
		});
		await settle();

		// yMax = max(p95, stable...) * 1.12 = 0.336; y(v) = PLOT_H - v / 0.336 * PLOT_H.
		const yMax = 0.3 * 1.12;
		const y = (v: number) => PLOT_H - (v / yMax) * PLOT_H;

		const band = document.querySelector('rect.band');
		expect(band).toBeTruthy();
		expect(Number(band?.getAttribute('y'))).toBeCloseTo(y(0.3), 1);
		expect(Number(band?.getAttribute('height'))).toBeCloseTo(y(0.1) - y(0.3), 1);

		const line = document.querySelector('path.series')?.getAttribute('d') ?? '';
		const pts = pairs(line);
		expect(pts).toHaveLength(2);
		for (const [, py] of pts) expect(py).toBeCloseTo(y(0.2), 1);
		// First day at the left edge, last at the right edge of a 524px plot.
		expect(pts[0][0]).toBeCloseTo(0, 1);
		expect(pts[1][0]).toBeCloseTo(WIDTH - 76, 1);
	});
});

describe('Decomposition geometry', () => {
	it('draws bar widths proportional to the means and no bar for a null stratum', async () => {
		render(Decomposition, {
			decomposition: {
				stable: { mean: 0.2, n: 10 },
				provider: { mean: 0.3, n: 10 },
				version: { mean: null, n: 0 },
				provider_ratio: 1.5,
				version_ratio: null,
				provider_ratio_ci: null,
				version_ratio_ci: null,
				provider_within: null,
				version_within: null
			}
		});
		await settle();
		// padding right 64 -> plot width 536; xMax = 0.3 * 1.3.
		const plotW = WIDTH - 64;
		const xMax = 0.3 * 1.3;
		const rects = [...document.querySelectorAll('.bars rect')];
		expect(rects).toHaveLength(2);
		const widths = rects.map((r) => Number(r.getAttribute('width')));
		expect(widths[0]).toBeCloseTo((0.2 / xMax) * plotW, 1);
		expect(widths[1]).toBeCloseTo((0.3 / xMax) * plotW, 1);
		expect(widths[1] / widths[0]).toBeCloseTo(1.5, 5);
	});
});

describe('Heatmap geometry', () => {
	it('maps the largest value to full opacity and keeps the smallest visible', async () => {
		render(Heatmap, {
			cells: [
				{ question_slug: 'q1', model_id: 'a', value: 0.4, n: 5 },
				{ question_slug: 'q1', model_id: 'b', value: 0.1, n: 5 },
				{ question_slug: 'q2', model_id: 'a', value: 0.2, n: 5 }
			],
			questions: { q1: { text: 'One', tags: [] }, q2: { text: 'Two', tags: [] } }
		});
		await settle();
		const rects = [...document.querySelectorAll('.cells rect')];
		expect(rects).toHaveLength(3);
		const opacity = rects.map((r) => Number(r.getAttribute('fill-opacity')));
		expect(Math.max(...opacity)).toBeCloseTo(1, 5);
		expect(Math.min(...opacity)).toBeCloseTo(0.06 + (0.1 / 0.4) * 0.94, 5);
		// Cells tile the plot: two columns across a 600 - 240 = 360px plot.
		const widths = rects.map((r) => Number(r.getAttribute('width')));
		expect(widths[0]).toBeCloseTo(360 / 2 - 1, 1);
	});
});
