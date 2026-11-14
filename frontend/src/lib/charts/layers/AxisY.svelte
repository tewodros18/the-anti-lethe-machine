<!--
	@component
	Left axis with horizontal gridlines.

	Reads the resolved scale from LayerCake rather than rebuilding one. Tick
	values come from `niceTicks` over the resolved domain, so the steps are
	round numbers.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';
	import { formatTick, niceTicks } from '../ticks';

	interface Props {
		/** Roughly how many ticks to aim for. */
		ticks?: number;
		/** Override the label text for a tick value. */
		format?: (value: number, all: readonly number[]) => string;
		/** Draw the gridline across the plot. */
		gridlines?: boolean;
		/** Pull labels left of the plot area by this many pixels. */
		dx?: number;
	}

	let { ticks = 5, format = formatTick, gridlines = true, dx = 8 }: Props = $props();

	const k = getLayerCakeContext();

	const values = $derived.by(() => {
		const domain = k.yDomain as unknown as number[];
		if (!domain || domain.length < 2) return [];
		return niceTicks(Number(domain[0]), Number(domain[1]), ticks);
	});
</script>

<g class="axis-y" aria-hidden="true">
	{#each values as value (value)}
		{@const y = k.yScale(value)}
		{#if Number.isFinite(y)}
			<g transform="translate(0,{y})">
				{#if gridlines}
					<line x1="0" x2={k.width} class="grid" />
				{/if}
				<text x={-dx} dy="0.32em" class="label">{format(value, values)}</text>
			</g>
		{/if}
	{/each}
</g>

<style>
	.grid {
		stroke: var(--rule);
		stroke-width: 1;
	}

	.label {
		fill: var(--ink-3);
		font-family: var(--font-mono);
		font-size: 10px;
		font-variant-numeric: tabular-nums;
		text-anchor: end;
	}
</style>
