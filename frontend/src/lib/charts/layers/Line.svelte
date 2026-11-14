<!--
	@component
	A line through the chart's data.

	Gaps are real: a point whose y is null is skipped rather than interpolated
	across, so a day with no contributing pairs does not become a straight line
	implying a measurement.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';
	import { line as d3Line } from 'd3-shape';

	interface Props {
		/** Stroke colour, usually a `var(--cN)` token. */
		stroke?: string;
		/** Stroke width in pixels. */
		width?: number;
		/** Dash pattern, e.g. `"3 3"`. */
		dash?: string | null;
		/** Read y from a different key than the chart's y accessor. */
		yKey?: string | null;
	}

	let { stroke = 'var(--c1)', width = 2, dash = null, yKey = null }: Props = $props();

	const k = getLayerCakeContext();

	const path = $derived.by(() => {
		const rows = (k.data ?? []) as Record<string, unknown>[];
		const value = (d: Record<string, unknown>): number =>
			yKey === null ? Number(k.yGet(d)) : Number(k.yScale(d[yKey] as never));
		const generator = d3Line<Record<string, unknown>>()
			.defined((d) => {
				const raw = yKey === null ? k.y(d) : d[yKey];
				return raw !== null && raw !== undefined && Number.isFinite(Number(raw));
			})
			.x((d) => Number(k.xGet(d)))
			.y(value);
		return generator(rows) ?? '';
	});
</script>

<path
	class="series"
	d={path}
	{stroke}
	stroke-width={width}
	stroke-dasharray={dash}
	aria-hidden="true"
/>

<style>
	.series {
		fill: none;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
</style>
