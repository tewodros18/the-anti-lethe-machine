<!--
	@component
	Three horizontal bars: sampling noise, host switch, model rebuild.

	The ratio sentence underneath is computed from the same numbers the bars
	draw. When a stratum has no observations its bar is absent and its ratio is
	an em dash, and the sentence says so in words rather than leaving a reader to
	infer that a missing bar meant zero drift.
-->
<script lang="ts">
	import { LayerCake, Svg } from 'layercake';
	import { scaleBand } from 'd3-scale';
	import AxisX from './layers/AxisX.svelte';
	import Bars from './layers/Bars.svelte';
	import { EM_DASH, fmt, fmtInt, fmtRatio } from '$lib/data/format';
	import type { Decomposition } from '$lib/data/types';

	/** `1.20×` with its interval, or the interval's absence said plainly. */
	function withInterval(ratio: number | null, ci: [number, number] | null): string {
		if (ratio === null) return EM_DASH;
		if (ci === null) return `${fmtRatio(ratio)} (too few pairs for an interval)`;
		return `${fmtRatio(ratio)} (95% interval ${ci[0].toFixed(2)}–${ci[1].toFixed(2)})`;
	}

	interface Props {
		decomposition: Decomposition;
		height?: number;
	}

	let { decomposition, height = 170 }: Props = $props();

	interface Row {
		label: string;
		mean: number | null;
		n: number;
		color: string;
	}

	const rows = $derived.by<Row[]>(() => [
		{
			label: 'Same build, same host',
			mean: decomposition.stable.mean,
			n: decomposition.stable.n,
			color: 'var(--c1)'
		},
		{
			label: 'Same build, new host',
			mean: decomposition.provider.mean,
			n: decomposition.provider.n,
			color: 'var(--c5)'
		},
		{
			label: 'New build',
			mean: decomposition.version.mean,
			n: decomposition.version.n,
			color: 'var(--c2)'
		}
	]);

	const xMax = $derived(Math.max(0.02, ...rows.map((row) => row.mean ?? 0)) * 1.3);

	let showTable = $state(false);

	/**
	 * The headline sentence. Every clause is conditional on there being data
	 * behind it, because a stratum with no observations has no ratio.
	 */
	const sentence = $derived.by(() => {
		const parts: string[] = [];
		const stable = decomposition.stable.mean;
		if (stable === null) {
			return 'There are not yet enough same-build, same-host pairs to establish a noise floor, so no ratio can be computed.';
		}
		if (decomposition.provider.n === 0) {
			parts.push('No host switches were observed in this window.');
		} else if (decomposition.provider_ratio !== null) {
			const within = decomposition.provider_within;
			if (within !== null) {
				parts.push(
					`Within a model, changing the inference host moves an answer a median ${fmtRatio(within.median)} as far as sampling noise alone (middle half of models ${within.q25.toFixed(2)}–${within.q75.toFixed(2)}×; ${fmtInt(within.above_one)} of ${fmtInt(within.n)} models above 1×).`
				);
				parts.push(
					`Pooled over all ${fmtInt(decomposition.provider.n)} host-switch pairs the ratio is ${withInterval(decomposition.provider_ratio, decomposition.provider_ratio_ci)}, but that compares the models that get switched with the ones that never do.`
				);
			} else {
				parts.push(
					`Changing the inference host moves an answer ${withInterval(decomposition.provider_ratio, decomposition.provider_ratio_ci)} as far as sampling noise alone, across ${fmtInt(decomposition.provider.n)} such pairs.`
				);
				const ci = decomposition.provider_ratio_ci;
				if (ci !== null && ci[0] <= 1) {
					parts.push(
						'That interval includes 1×, so this window cannot distinguish a host switch from noise.'
					);
				}
			}
		}
		if (decomposition.version.n === 0) {
			parts.push(
				'No model rebuilds occurred in this window, so there is no rebuild figure to compare against.'
			);
		} else if (decomposition.version_ratio !== null) {
			parts.push(
				`A new model build moves it ${withInterval(decomposition.version_ratio, decomposition.version_ratio_ci)} as far, across ${fmtInt(decomposition.version.n)} pairs.`
			);
		}
		return parts.join(' ');
	});
</script>

<div class="head">
	<button
		class="btn"
		aria-pressed={showTable}
		onclick={() => (showTable = !showTable)}
		type="button">Show as table</button
	>
</div>

{#if showTable}
	<table>
		<caption class="sr-only">Mean distance by cause of change</caption>
		<thead>
			<tr>
				<th scope="col">Cause of change</th>
				<th scope="col">Mean distance</th>
				<th scope="col">Pairs</th>
				<th scope="col">vs noise</th>
			</tr>
		</thead>
		<tbody>
			{#each rows as row, i (row.label)}
				<tr>
					<th scope="row">{row.label}</th>
					<td class:nil={row.mean === null}>{fmt(row.mean)}</td>
					<td>{fmtInt(row.n)}</td>
					<td>
						{#if i === 0}
							baseline
						{:else if i === 1}
							{fmtRatio(decomposition.provider_ratio)}
						{:else}
							{fmtRatio(decomposition.version_ratio)}
						{/if}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{:else}
	<div class="chart" style:height="{height}px">
		<LayerCake
			data={rows}
			x="mean"
			y="label"
			yScale={scaleBand().paddingInner(0.3).paddingOuter(0.15)}
			xDomain={[0, xMax]}
			padding={{ top: 8, right: 64, bottom: 32, left: 0 }}
		>
			<Svg label="Mean distance by cause of change" describedBy="decomp-desc">
				{#snippet title()}Mean distance by cause of change{/snippet}
				<desc id="decomp-desc"
					>Three bars comparing the mean distance between consecutive archived answers when nothing
					changed, when the serving host changed, and when the model build changed.</desc
				>
				<AxisX ticks={4} />
				<Bars fill={(row) => String(row.color)} label={(row) => fmt(row.mean as number)} />
			</Svg>
		</LayerCake>
	</div>
	<!-- Bar labels are drawn inside the SVG; the row names live here so they
	     wrap and stay legible at narrow widths. -->
	<ul class="keys">
		{#each rows as row (row.label)}
			<li>
				<span class="swatch" style:background={row.color} aria-hidden="true"></span>
				<span class="name">{row.label}</span>
				<span class="meta">{row.n === 0 ? 'no pairs observed' : `${fmtInt(row.n)} pairs`}</span>
			</li>
		{/each}
	</ul>
{/if}

<p class="verdict">{sentence}</p>

<div class="ratios">
	{#if decomposition.provider_within}
		<div class="ratio">
			<span class="rk">host effect, within model</span>
			<span class="rv">{fmtRatio(decomposition.provider_within.median)}</span>
			<span class="ci"
				>median of {fmtInt(decomposition.provider_within.n)} models · {fmtInt(
					decomposition.provider_within.above_one
				)} above 1×</span
			>
		</div>
	{/if}
	<div class="ratio">
		<span class="rk">host effect{decomposition.provider_within ? ', pooled' : ''}</span>
		<span class="rv" class:nil={decomposition.provider_ratio === null}
			>{decomposition.provider_ratio === null
				? EM_DASH
				: fmtRatio(decomposition.provider_ratio)}</span
		>
		<span class="ci" class:nil={decomposition.provider_ratio_ci === null}
			>{decomposition.provider_ratio_ci === null
				? decomposition.provider_ratio === null
					? ''
					: 'no interval: too few pairs'
				: `95% ${decomposition.provider_ratio_ci[0].toFixed(2)}–${decomposition.provider_ratio_ci[1].toFixed(2)}`}</span
		>
	</div>
	<div class="ratio">
		<span class="rk">rebuild effect</span>
		<span class="rv" class:nil={decomposition.version_ratio === null}
			>{decomposition.version_ratio === null
				? EM_DASH
				: fmtRatio(decomposition.version_ratio)}</span
		>
		<span class="ci" class:nil={decomposition.version_ratio_ci === null}
			>{decomposition.version_ratio_ci === null
				? decomposition.version_ratio === null
					? ''
					: 'no interval: too few pairs'
				: `95% ${decomposition.version_ratio_ci[0].toFixed(2)}–${decomposition.version_ratio_ci[1].toFixed(2)}`}</span
		>
	</div>
</div>

<style>
	.head {
		display: flex;
		justify-content: flex-end;
	}

	.chart {
		position: relative;
	}

	.keys {
		list-style: none;
		margin: 0.5em 0 0;
		padding: 0;
		display: grid;
		gap: 0.25em;
		font-family: var(--font-mono);
		font-size: 0.74rem;
	}

	.keys li {
		display: flex;
		align-items: baseline;
		gap: 0.5em;
	}

	.swatch {
		width: 10px;
		height: 10px;
		border-radius: 1px;
		flex: none;
		transform: translateY(1px);
	}

	.name {
		color: var(--ink-2);
	}

	.meta {
		color: var(--ink-3);
		margin-left: auto;
	}

	.verdict {
		margin: 1em 0 0.9em;
		font-family: var(--font-display);
		font-size: 1.02rem;
		line-height: 1.45;
		color: var(--ink);
	}

	.ratios {
		display: flex;
		gap: 2.5em;
		flex-wrap: wrap;
		border-top: 1px solid var(--rule);
		padding-top: 0.8em;
	}

	.ratio {
		display: flex;
		flex-direction: column;
		gap: 0.1em;
	}

	.rk {
		font-family: var(--font-mono);
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--ink-3);
	}

	.rv {
		font-family: var(--font-mono);
		font-size: 1.6rem;
		font-variant-numeric: tabular-nums;
		color: var(--ink);
	}

	.ci {
		font-family: var(--font-mono);
		font-size: 0.68rem;
		font-variant-numeric: tabular-nums;
		color: var(--ink-2);
	}
</style>
