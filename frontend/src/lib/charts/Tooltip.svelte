<!--
	@component
	The floating tooltip panel, clamped to its container.

	One implementation shared by every chart, so hover panels cannot drift apart
	in style or positioning.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** Position within the plot area, in pixels. */
		x: number;
		y: number;
		/** Plot dimensions, used to keep the panel inside them. */
		width: number;
		height: number;
		children: Snippet;
	}

	let { x, y, width, height, children }: Props = $props();

	const PANEL_WIDTH = 190;
	const OFFSET = 12;

	/** Flip to the left of the cursor when there is no room on the right. */
	const left = $derived(
		x + OFFSET + PANEL_WIDTH > width ? Math.max(0, x - OFFSET - PANEL_WIDTH) : x + OFFSET
	);

	const top = $derived(Math.max(0, Math.min(y - 10, Math.max(0, height - 80))));
</script>

<div class="tooltip" style:left="{left}px" style:top="{top}px" style:width="{PANEL_WIDTH}px">
	{@render children()}
</div>

<style>
	.tooltip {
		position: absolute;
		pointer-events: none;
		background: var(--plate);
		border: 1px solid var(--rule-2);
		border-radius: var(--radius);
		box-shadow: 0 4px 14px rgb(0 0 0 / 0.14);
		padding: 0.5em 0.6em;
		font-family: var(--font-mono);
		font-size: 0.72rem;
		line-height: 1.45;
		font-variant-numeric: tabular-nums;
		color: var(--ink);
		z-index: 10;
	}
</style>
