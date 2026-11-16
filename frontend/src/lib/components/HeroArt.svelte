<!--
	@component
	The hero illustration: a contour field. Rings nested around one fixed mark,
	round at the centre and bending further out of true the further they sit
	from it, which is the register's subject as a shape: a benchmark, and
	readings that wander the longer they run. One ring is picked out in the
	accent, the way a survey map picks out an index contour. Drawn as ink
	hairlines at low opacity so it sits in the paper rather than on it, and it
	fades out towards the text. It is decorative, so it is hidden from
	assistive technology.
-->
<script lang="ts">
	import { contours } from '$lib/data/contour';

	const W = 560;
	const H = 360;
	const CX = 372;
	const CY = 186;
	const COUNT = 24;
	const INDEX = 8;

	const rings = contours({ count: COUNT, cx: CX, cy: CY, r0: 12, step: 13, seed: 11 });

	/** Inner rings darker, outer ones dissolving into the paper. */
	const alpha = (drift: number) => Math.round((0.62 - 0.46 * drift) * 100) / 100;
</script>

<svg
	class="canvas"
	viewBox="0 0 {W} {H}"
	preserveAspectRatio="xMidYMid slice"
	aria-hidden="true"
	focusable="false"
>
	<defs>
		<linearGradient id="hero-fade" x1="0" x2="1" y1="0" y2="0">
			<stop offset="0" stop-color="#fff" stop-opacity="0" />
			<stop offset="0.38" stop-color="#fff" stop-opacity="1" />
		</linearGradient>
		<mask id="hero-mask">
			<rect width={W} height={H} fill="url(#hero-fade)" />
		</mask>
	</defs>
	<g class="field" mask="url(#hero-mask)">
		{#each rings as ring (ring.k)}
			<path d={ring.d} class:index={ring.k === INDEX} style:opacity={alpha(ring.drift)} />
		{/each}
		<circle class="mark" cx={CX} cy={CY} r="3.2" />
	</g>
</svg>

<style>
	/* Fills whatever box it is given and crops the field rather than letterboxing
	   it, so beside a tall column of text it runs the column's full height. */
	.canvas {
		display: block;
		width: 100%;
		height: 100%;
	}

	.field path {
		fill: none;
		stroke: var(--ink);
		stroke-width: 0.8;
		stroke-linejoin: round;
	}

	.field path.index {
		stroke: var(--accent);
		stroke-width: 1.3;
		opacity: 0.95 !important;
	}

	.mark {
		fill: var(--accent);
	}
</style>
