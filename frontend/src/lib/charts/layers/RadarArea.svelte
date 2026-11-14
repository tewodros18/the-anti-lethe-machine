<!--
	@component
	One model's shape on the radar, plus its vertex points.

	Values arrive already scaled to 0–1 by the caller. A null axis value is an
	absent measurement, not a low one, so it is never drawn: the outline breaks
	at that axis and the shape loses its fill. Pulling a null vertex into the
	centre would draw a spike that reads as "worst on this axis", which is a
	claim the data does not make.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Props {
		/** One value per axis, in the same order as the web's axes. 0–1 or null. */
		values: readonly (number | null)[];
		color?: string;
		fillOpacity?: number;
		strokeWidth?: number;
		/** Accessible description of this shape. */
		label?: string;
	}

	let {
		values,
		color = 'var(--c1)',
		fillOpacity = 0.14,
		strokeWidth = 1.75,
		label
	}: Props = $props();

	const k = getLayerCakeContext();

	/** Spoke angle: twelve o'clock first, clockwise. Must match RadarWeb. */
	function angle(i: number): number {
		return (i / values.length) * Math.PI * 2 - Math.PI / 2;
	}

	const vertices = $derived.by(() =>
		values.map((value, i) => {
			const measured = value !== null && Number.isFinite(value);
			const radius = measured ? Number(k.rScale(value)) : 0;
			const a = angle(i);
			return { x: Math.cos(a) * radius, y: Math.sin(a) * radius, measured };
		})
	);

	const complete = $derived(vertices.every((v) => v.measured));

	/**
	 * The outline. A complete shape is one closed path. With a gap, each run of
	 * measured vertices becomes its own open sub-path, and the run that wraps
	 * past the last axis continues into the first so the gap sits where the
	 * missing axis is and nowhere else.
	 */
	const outline = $derived.by(() => {
		if (vertices.length === 0) return '';
		if (complete) {
			return vertices.map((v, i) => `${i === 0 ? 'M' : 'L'}${v.x},${v.y}`).join(' ') + ' Z';
		}
		// Rotate so the sequence starts just after a gap; then runs never wrap.
		const n = vertices.length;
		let start = vertices.findIndex((v, i) => !vertices[(i - 1 + n) % n].measured && v.measured);
		if (start < 0) return '';
		const parts: string[] = [];
		let open = false;
		for (let step = 0; step < n; step += 1) {
			const v = vertices[(start + step) % n];
			if (!v.measured) {
				open = false;
				continue;
			}
			parts.push(`${open ? 'L' : 'M'}${v.x},${v.y}`);
			open = true;
		}
		return parts.join(' ');
	});
</script>

<g class="radar-area" transform="translate({k.width / 2},{k.height / 2})">
	{#if label}<title>{label}</title>{/if}
	<path
		class="outline"
		class:open={!complete}
		d={outline}
		fill={complete ? color : 'none'}
		fill-opacity={fillOpacity}
		stroke={color}
		stroke-width={strokeWidth}
	/>
	{#each vertices as vertex, i (i)}
		{#if vertex.measured}
			<circle cx={vertex.x} cy={vertex.y} r="2.75" fill={color} />
		{/if}
	{/each}
</g>

<style>
	.outline {
		stroke-linejoin: round;
		stroke-linecap: round;
	}
</style>
