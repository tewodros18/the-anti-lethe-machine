<!--
	@component
	Vertical rules at given x values: event markers for repoints and host switches.

	Sits under the data line, so an event is context for the trace rather than
	competing with it.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Props {
		/** x values in data units, e.g. `Date` objects on a time scale. */
		days: readonly unknown[];
		stroke?: string;
		width?: number;
		dash?: string | null;
		opacity?: number;
	}

	let { days, stroke = 'var(--c2)', width = 1.5, dash = null, opacity = 0.85 }: Props = $props();

	const k = getLayerCakeContext();

	const positions = $derived.by(() =>
		days.map((day) => Number(k.xScale(day as never))).filter((x) => Number.isFinite(x))
	);
</script>

<g class="rails" aria-hidden="true">
	{#each positions as x, i (i)}
		<line
			x1={x}
			x2={x}
			y1="0"
			y2={k.height}
			{stroke}
			stroke-width={width}
			stroke-dasharray={dash}
			{opacity}
		/>
	{/each}
</g>
