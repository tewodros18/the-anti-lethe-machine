<!--
	@component
	A bare inline line, no axes, for use inside table rows.

	Deliberately unlabelled: it shows shape, not value. The adjacent table cells
	carry the numbers, so a reader never has to estimate from this.
-->
<script lang="ts">
	import { LayerCake, Svg } from 'layercake';
	import Line from './layers/Line.svelte';

	interface Props {
		/** One value per day, nulls allowed and left as gaps. */
		values: readonly (number | null)[];
		stroke?: string;
		width?: number;
		height?: number;
		/** Shared upper bound, so sparklines in one table are comparable. */
		max?: number | null;
		/** Accessible summary; the chart is `aria-hidden` without one. */
		label?: string;
	}

	let {
		values,
		stroke = 'var(--c1)',
		width = 84,
		height = 20,
		max = null,
		label
	}: Props = $props();

	const rows = $derived.by(() => values.map((value, i) => ({ i, value })));

	const upper = $derived.by(() => {
		if (max !== null && Number.isFinite(max)) return max;
		const present = values.filter((v): v is number => v !== null && Number.isFinite(v));
		return present.length ? Math.max(...present) * 1.1 : 1;
	});

	const measured = $derived(values.some((v) => v !== null));
</script>

<div class="spark" style:width="{width}px" style:height="{height}px">
	{#if measured}
		<LayerCake
			data={rows}
			x="i"
			y="value"
			yDomain={[0, upper]}
			padding={{ top: 2, right: 1, bottom: 2, left: 1 }}
		>
			<Svg label={label ?? undefined}>
				<Line {stroke} width={1.25} />
			</Svg>
		</LayerCake>
	{/if}
</div>

<style>
	.spark {
		position: relative;
		display: inline-block;
		vertical-align: middle;
	}
</style>
