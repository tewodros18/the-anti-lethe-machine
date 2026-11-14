<!--
	@component
	Horizontal bars: a band y scale against a linear x scale from zero.

	A null value draws no bar and an em dash where the value label would be, so
	an unmeasurable stratum is visibly absent instead of looking like zero.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';
	import { EM_DASH } from '$lib/data/format';

	interface Props {
		/** Per-row fill colour, keyed by the row's y value. */
		fill?: (row: Record<string, unknown>) => string;
		/** Text drawn at the end of each bar. */
		label?: (row: Record<string, unknown>) => string;
		/** Inset applied to each band, in pixels. */
		inset?: number;
	}

	let { fill = () => 'var(--c1)', label, inset = 4 }: Props = $props();

	const k = getLayerCakeContext();

	const bars = $derived.by(() => {
		const rows = (k.data ?? []) as Record<string, unknown>[];
		const scale = k.yScale as unknown as { bandwidth?: () => number };
		const band = typeof scale.bandwidth === 'function' ? scale.bandwidth() : 16;
		const zero = Number(k.xScale(0));

		return rows.map((row) => {
			const raw = k.x(row);
			const measurable = raw !== null && raw !== undefined && Number.isFinite(Number(raw));
			const end = measurable ? Number(k.xGet(row)) : zero;
			return {
				row,
				y: Number(k.yGet(row)) + inset / 2,
				height: Math.max(1, band - inset),
				x: Math.min(zero, end),
				width: measurable ? Math.abs(end - zero) : 0,
				measurable,
				end
			};
		});
	});
</script>

<g class="bars">
	{#each bars as bar, i (i)}
		{#if bar.measurable}
			<rect x={bar.x} y={bar.y} width={bar.width} height={bar.height} fill={fill(bar.row)} />
		{/if}
		{#if label}
			<text
				x={bar.measurable ? bar.end + 6 : Number(k.xScale(0)) + 6}
				y={bar.y + bar.height / 2}
				dy="0.32em"
				class="value"
				class:nil={!bar.measurable}>{bar.measurable ? label(bar.row) : EM_DASH}</text
			>
		{/if}
	{/each}
</g>

<style>
	.value {
		fill: var(--ink);
		font-family: var(--font-mono);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}

	.value.nil {
		fill: var(--ink-3);
	}
</style>
