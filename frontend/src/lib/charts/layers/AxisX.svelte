<!--
	@component
	Bottom axis.

	Works for time, linear and band scales by asking the resolved scale what it
	is: a scale with `.ticks()` provides its own values, a band scale's values
	are its domain, thinned so labels cannot collide.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';
	import { thin } from '../ticks';

	interface Props {
		/** Roughly how many labels to show. */
		ticks?: number;
		/** Label formatter. Receives the raw tick value. */
		format?: (value: never) => string;
		/** Rotate labels, for long categorical names. */
		rotate?: number;
		/** Draw a vertical gridline at each tick. */
		gridlines?: boolean;
	}

	let {
		ticks = 7,
		format = (value: never) => String(value),
		rotate = 0,
		gridlines = false
	}: Props = $props();

	const k = getLayerCakeContext();

	/** Tick values, from whichever kind of scale LayerCake resolved. */
	const values = $derived.by(() => {
		const scale = k.xScale as unknown as {
			ticks?: (count: number) => unknown[];
			bandwidth?: () => number;
		};
		if (typeof scale.bandwidth === 'function') {
			return thin(k.xDomain as unknown[], ticks);
		}
		if (typeof scale.ticks === 'function') {
			return scale.ticks(ticks);
		}
		return thin(k.xDomain as unknown[], ticks);
	});

	/** Band scales label the centre of the band; others label the point. */
	const offset = $derived.by(() => {
		const scale = k.xScale as unknown as { bandwidth?: () => number };
		return typeof scale.bandwidth === 'function' ? scale.bandwidth() / 2 : 0;
	});
</script>

<g class="axis-x" transform="translate(0,{k.height})" aria-hidden="true">
	<line x1="0" x2={k.width} class="baseline" />
	{#each values as value, i (i)}
		{@const x = Number(k.xScale(value as never)) + offset}
		{#if Number.isFinite(x)}
			<g transform="translate({x},0)">
				{#if gridlines}
					<line y1={-k.height} y2="0" class="grid" />
				{/if}
				<line y1="0" y2="4" class="tick" />
				{#if rotate}
					<text
						y="7"
						class="label"
						transform="rotate({rotate})"
						text-anchor="end"
						dominant-baseline="middle">{format(value as never)}</text
					>
				{:else}
					<text y="16" class="label" text-anchor="middle">{format(value as never)}</text>
				{/if}
			</g>
		{/if}
	{/each}
</g>

<style>
	.baseline,
	.tick {
		stroke: var(--rule-2);
		stroke-width: 1;
	}

	.grid {
		stroke: var(--rule);
		stroke-width: 1;
	}

	.label {
		fill: var(--ink-3);
		font-family: var(--font-mono);
		font-size: 10px;
		font-variant-numeric: tabular-nums;
	}
</style>
