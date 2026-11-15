<!--
	@component
	The hero illustration: a mound of stippled dots with a survey mark planted on
	its crest, a flag on a thin mast. A benchmark in the surveyor's sense, which
	is what this register is: a fixed mark that later readings are measured
	against. Drawn in the ink colour at low opacity so it sits in the paper
	rather than on it, and it is decorative, so it is hidden from assistive
	technology.
-->
<script lang="ts">
	import { stipple } from '$lib/data/stipple';

	const W = 520;
	const H = 300;
	const BASE = 268;

	const dots = stipple(2600, W, BASE, 7);

	// The mast stands at the crest.
	const mastX = 322;
	const mastTop = 48;
	const mastBottom = 150;
</script>

<svg class="art" viewBox="0 0 {W} {H}" width={W} height={H} aria-hidden="true" focusable="false">
	<g class="mound">
		{#each dots as dot, i (i)}
			<circle cx={dot.x} cy={dot.y} r={dot.r} />
		{/each}
	</g>
	<g class="mark">
		<line x1={mastX} y1={mastTop} x2={mastX} y2={mastBottom} />
		<path d="M{mastX + 1} {mastTop + 2} l 46 11 l -46 11 z" />
		<line x1={mastX - 14} y1={mastBottom} x2={mastX + 14} y2={mastBottom} />
	</g>
</svg>

<style>
	.art {
		display: block;
		max-width: 100%;
		height: auto;
	}

	.mound circle {
		fill: var(--ink);
		opacity: 0.34;
	}

	.mark line {
		stroke: var(--ink);
		stroke-width: 1.4;
		stroke-linecap: round;
		opacity: 0.7;
	}

	.mark path {
		fill: var(--accent);
		opacity: 0.85;
	}
</style>
