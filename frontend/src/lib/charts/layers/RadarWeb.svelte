<!--
	@component
	The polar grid: concentric rings, one spoke per axis, and axis labels.

	Radius comes from LayerCake's resolved `r` scale, so the web and the data
	shapes cannot disagree about where 1.0 sits. The innermost ring is drawn at
	the caller's floor, the radius below which nothing is ever plotted, so the
	centre reads as "off the scale" rather than as a value.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Props {
		/** Axis labels, in order, one spoke each. */
		axes: readonly string[];
		/** Number of concentric rings between the floor and the rim. */
		levels?: number;
		/** Scaled value of the innermost ring. */
		floor?: number;
		/** Per-axis flag: true when the shown models do not differ on that axis. */
		muted?: readonly boolean[];
	}

	let { axes, levels = 4, floor = 0, muted = [] }: Props = $props();

	const k = getLayerCakeContext();

	/** Spoke angle: twelve o'clock first, clockwise. Must match RadarArea. */
	function angle(i: number): number {
		return (i / axes.length) * Math.PI * 2 - Math.PI / 2;
	}

	const outer = $derived(Number(k.rScale(1)));

	const rings = $derived.by(() =>
		Array.from({ length: levels }, (_, level) => {
			const fraction = floor + (1 - floor) * (level / Math.max(1, levels - 1));
			const radius = Number(k.rScale(fraction));
			const points = axes
				.map((_, i) => `${Math.cos(angle(i)) * radius},${Math.sin(angle(i)) * radius}`)
				.join(' ');
			return { fraction, radius, points };
		})
	);

	const spokes = $derived.by(() =>
		axes.map((label, i) => {
			const a = angle(i);
			const cos = Math.cos(a);
			const sin = Math.sin(a);
			return {
				label,
				muted: muted[i] === true,
				x2: cos * outer,
				y2: sin * outer,
				// Push labels clear of the rim.
				lx: cos * (outer + 14),
				ly: sin * (outer + 14),
				anchor: Math.abs(cos) < 0.25 ? 'middle' : cos > 0 ? 'start' : 'end'
			};
		})
	);
</script>

<g class="web" transform="translate({k.width / 2},{k.height / 2})" aria-hidden="true">
	{#each rings as ring (ring.fraction)}
		<polygon points={ring.points} class="ring" class:rim={ring.fraction === 1} />
	{/each}
	{#each spokes as spoke (spoke.label)}
		<line x1="0" y1="0" x2={spoke.x2} y2={spoke.y2} class="spoke" />
		<text
			x={spoke.lx}
			y={spoke.ly}
			text-anchor={spoke.anchor}
			dominant-baseline="middle"
			class="axis-label"
			class:muted={spoke.muted}>{spoke.label}</text
		>
	{/each}
</g>

<style>
	.ring {
		fill: none;
		stroke: var(--rule);
		stroke-width: 1;
	}

	.ring.rim {
		stroke: var(--rule-2);
	}

	.spoke {
		stroke: var(--rule-2);
		stroke-width: 1;
	}

	.axis-label {
		fill: var(--ink-3);
		font-family: var(--font-mono);
		font-size: 9.5px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.axis-label.muted {
		fill: var(--rule-2);
		font-style: italic;
	}
</style>
