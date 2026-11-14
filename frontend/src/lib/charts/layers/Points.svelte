<!--
	@component
	Circles at explicit positions, for marking individual events on a series.

	Takes its own rows rather than reading the chart's data, because event
	markers are a different set from the line's points.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Point {
		/** x value in data units. */
		x: unknown;
		/** y value in data units; null points are not drawn. */
		y: number | null;
		fill?: string;
		title?: string;
	}

	interface Props {
		data: readonly Point[];
		r?: number;
		stroke?: string;
		strokeWidth?: number;
		fill?: string;
	}

	let {
		data,
		r = 4,
		stroke = 'var(--plate)',
		strokeWidth = 1.25,
		fill = 'var(--c1)'
	}: Props = $props();

	const k = getLayerCakeContext();

	const placed = $derived.by(() =>
		data
			.map((point) => ({
				cx: Number(k.xScale(point.x as never)),
				cy: point.y === null ? Number.NaN : Number(k.yScale(point.y)),
				fill: point.fill ?? fill,
				title: point.title
			}))
			.filter((p) => Number.isFinite(p.cx) && Number.isFinite(p.cy))
	);
</script>

<g class="points">
	{#each placed as point, i (i)}
		<circle cx={point.cx} cy={point.cy} {r} fill={point.fill} {stroke} stroke-width={strokeWidth}>
			{#if point.title}<title>{point.title}</title>{/if}
		</circle>
	{/each}
</g>
