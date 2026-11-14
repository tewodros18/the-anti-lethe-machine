<!--
	@component
	Several polylines on one pair of scales, one per group, with the chart's
	x/y accessors applied to each group's own rows.

	`Line` draws the chart's data as a single series. This layer is for the case
	where every group is its own series over the same plane, which is what a
	trajectory plot needs: one path per model through the answer space.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';
	import { line as d3Line } from 'd3-shape';

	interface Group {
		key: string;
		/** Rows the chart's x/y accessors understand; any object shape. */
		rows: readonly object[];
		stroke: string;
		width?: number;
		opacity?: number;
		dash?: string | null;
	}

	interface Props {
		groups: readonly Group[];
	}

	let { groups }: Props = $props();

	const k = getLayerCakeContext();

	const paths = $derived.by(() => {
		const generator = d3Line<object>()
			.defined((d) => Number.isFinite(Number(k.xGet(d))) && Number.isFinite(Number(k.yGet(d))))
			.x((d) => Number(k.xGet(d)))
			.y((d) => Number(k.yGet(d)));
		return groups.map((group) => ({ ...group, d: generator([...group.rows]) ?? '' }));
	});
</script>

<g class="paths" aria-hidden="true">
	{#each paths as path (path.key)}
		<path
			d={path.d}
			stroke={path.stroke}
			stroke-width={path.width ?? 1.5}
			stroke-dasharray={path.dash ?? null}
			opacity={path.opacity ?? 0.9}
			fill="none"
			stroke-linejoin="round"
			stroke-linecap="round"
		/>
	{/each}
</g>
