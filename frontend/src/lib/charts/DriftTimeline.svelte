<!--
	@component
	The stable-stratum trace against its own noise band.

	Reading order, back to front: the p05–p95 noise band, the median rule, event
	rails, then the line, then event markers. The band is behind everything
	because its job is to say which part of the line means nothing.

	Only the STABLE stratum is drawn as the line. Mixing strata into one trace is
	the error this whole project exists to avoid, so provider and version days
	appear as rails and markers instead.
-->
<script lang="ts">
	import { LayerCake, Html, Svg } from 'layercake';
	import { scaleTime } from 'd3-scale';
	import AxisX from './layers/AxisX.svelte';
	import AxisY from './layers/AxisY.svelte';
	import Area from './layers/Area.svelte';
	import HoverLayer from './layers/HoverLayer.svelte';
	import Line from './layers/Line.svelte';
	import Points from './layers/Points.svelte';
	import Rails from './layers/Rails.svelte';
	import RuleY from './layers/RuleY.svelte';
	import Legend from './Legend.svelte';
	import { EM_DASH, fmt, fmtInt, longDay, parseDay, shortDay } from '$lib/data/format';
	import type { NoiseStats, ProviderEvent, TimelinePoint, VersionEvent } from '$lib/data/types';

	interface Props {
		timeline: readonly TimelinePoint[];
		noise: NoiseStats;
		versionEvents: readonly VersionEvent[];
		providerEvents: readonly ProviderEvent[];
		height?: number;
	}

	let { timeline, noise, versionEvents, providerEvents, height = 300 }: Props = $props();

	interface Row extends TimelinePoint {
		date: Date;
	}

	const rows = $derived.by<Row[]>(() =>
		timeline.map((point) => ({ ...point, date: parseDay(point.day) }))
	);

	/** Event days as Date objects, deduplicated, for the rails. */
	const versionDays = $derived.by(() =>
		[...new Set(versionEvents.map((event) => event.day))].map(parseDay)
	);

	const providerDays = $derived.by(() =>
		[...new Set(providerEvents.map((event) => event.day))].map(parseDay)
	);

	/**
	 * Markers at each event day, placed at that day's measured distance within
	 * the stratum the event belongs to.
	 */
	const eventPoints = $derived.by(() => {
		const byDay = new Map(timeline.map((point) => [point.day, point]));
		const out: { x: Date; y: number | null; fill: string; title: string }[] = [];
		for (const day of new Set(providerEvents.map((e) => e.day))) {
			const point = byDay.get(day);
			if (point?.provider === null || point?.provider === undefined) continue;
			out.push({
				x: parseDay(day),
				y: point.provider,
				fill: 'var(--c5)',
				title: `${longDay(day)}: host switch, mean distance ${fmt(point.provider)}`
			});
		}
		for (const day of new Set(versionEvents.map((e) => e.day))) {
			const point = byDay.get(day);
			if (point?.version === null || point?.version === undefined) continue;
			out.push({
				x: parseDay(day),
				y: point.version,
				fill: 'var(--c2)',
				title: `${longDay(day)}: model rebuild, mean distance ${fmt(point.version)}`
			});
		}
		return out;
	});

	/** Upper bound: the band, the trace and every marker must all fit. */
	const yMax = $derived.by(() => {
		const candidates = [
			noise.p95 ?? 0,
			...rows.map((r) => r.stable ?? 0),
			...rows.map((r) => r.provider ?? 0),
			...rows.map((r) => r.version ?? 0),
			...eventPoints.map((p) => p.y ?? 0)
		];
		const peak = Math.max(0.02, ...candidates);
		return peak * 1.12;
	});

	let showTable = $state(false);

	const legend = $derived([
		{
			label: 'Same build, same host',
			color: 'var(--c1)',
			shape: 'line' as const,
			note: `n=${fmtInt(noise.n)}`
		},
		{ label: 'Noise band p05–p95', color: 'var(--band)', shape: 'swatch' as const },
		{
			label: `Host switch (${providerDays.length})`,
			color: 'var(--c5)',
			shape: 'dash' as const
		},
		{
			label: `Model rebuild (${versionDays.length})`,
			color: 'var(--c2)',
			shape: 'line' as const
		}
	]);

	const description = $derived(
		`Mean distance between consecutive archived answers, for pairs where the model build and ` +
			`serving host both stayed the same, from ${timeline.at(0)?.day ?? EM_DASH} to ` +
			`${timeline.at(-1)?.day ?? EM_DASH}. The shaded band is the 5th to 95th percentile of ` +
			`that same distribution. Vertical rules mark ${providerDays.length} host switches and ` +
			`${versionDays.length} model rebuilds.`
	);
</script>

<div class="head">
	<Legend entries={legend} />
	<button
		class="btn"
		aria-pressed={showTable}
		onclick={() => (showTable = !showTable)}
		type="button">Show as table</button
	>
</div>

{#if showTable}
	<div class="table-wrap">
		<table>
			<caption class="sr-only">Mean distance per day within each stratum</caption>
			<thead>
				<tr>
					<th scope="col">Day</th>
					<th scope="col">Same host</th>
					<th scope="col">n</th>
					<th scope="col">Host switch</th>
					<th scope="col">n</th>
					<th scope="col">Rebuild</th>
					<th scope="col">n</th>
				</tr>
			</thead>
			<tbody>
				{#each timeline as point (point.day)}
					<tr>
						<th scope="row">{point.day}</th>
						<td class:nil={point.stable === null}>{fmt(point.stable)}</td>
						<td>{fmtInt(point.n_stable)}</td>
						<td class:nil={point.provider === null}>{fmt(point.provider)}</td>
						<td>{fmtInt(point.n_provider)}</td>
						<td class:nil={point.version === null}>{fmt(point.version)}</td>
						<td>{fmtInt(point.n_version)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<div class="scroll">
		<div class="chart" style:height="{height}px">
			<LayerCake
				data={rows}
				x="date"
				y="stable"
				xScale={scaleTime()}
				yDomain={[0, yMax]}
				padding={{ top: 16, right: 20, bottom: 40, left: 56 }}
			>
				<Svg label="Drift timeline" describedBy="drift-timeline-desc">
					{#snippet title()}Drift timeline{/snippet}
					<desc id="drift-timeline-desc">{description}</desc>
					<AxisY ticks={5} />
					<AxisX ticks={7} format={shortDay} />
					<!-- Band first: it is the backdrop the trace is read against. -->
					<Area y0={noise.p05} y1={noise.p95} fill="var(--band)" opacity={0.45} />
					<RuleY value={noise.median} dash="3 3" label="median" />
					<Rails days={providerDays} stroke="var(--c5)" width={1} dash="2 3" />
					<Rails days={versionDays} stroke="var(--c2)" width={1.5} />
					<Line stroke="var(--c1)" width={2} />
					<Points data={eventPoints} r={5.5} />
				</Svg>
				<Html>
					<HoverLayer
						data={rows}
						snippet={tip}
						describe={(row) =>
							`${longDay(row.day)}: same-host distance ${fmt(row.stable)} over ` +
							`${fmtInt(row.n_stable)} pairs`}
					/>
				</Html>
			</LayerCake>
		</div>
	</div>
{/if}

{#snippet tip(row: Row)}
	<div class="tip-day">{longDay(row.day)}</div>
	<div class="tip-row">
		<span class="k">same host</span>
		<span class:nil={row.stable === null}>{fmt(row.stable)}</span>
	</div>
	<div class="tip-row"><span class="k">pairs</span><span>{fmtInt(row.n_stable)}</span></div>
	{#if row.n_provider > 0}
		<div class="tip-row">
			<span class="k">host switch</span>
			<span class:nil={row.provider === null}>{fmt(row.provider)}</span>
		</div>
		<div class="tip-row"><span class="k">pairs</span><span>{fmtInt(row.n_provider)}</span></div>
	{/if}
	{#if row.n_version > 0}
		<div class="tip-row">
			<span class="k">rebuild</span>
			<span class:nil={row.version === null}>{fmt(row.version)}</span>
		</div>
		<div class="tip-row"><span class="k">pairs</span><span>{fmtInt(row.n_version)}</span></div>
	{/if}
{/snippet}

<style>
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1em;
		flex-wrap: wrap;
	}

	.scroll {
		overflow-x: auto;
	}

	.chart {
		position: relative;
		min-width: 320px;
	}

	.table-wrap {
		max-height: 420px;
		overflow: auto;
	}

	.tip-day {
		color: var(--ink-3);
		margin-bottom: 0.25em;
	}

	.tip-row {
		display: flex;
		justify-content: space-between;
		gap: 0.8em;
	}

	.tip-row .k {
		color: var(--ink-3);
	}
</style>
