<!--
	@component
	Pointer and keyboard reading for time-series charts, in an `<Html>` layer.

	Hover lives in HTML rather than SVG so the tooltip is a real DOM node and
	positions without SVG coordinate maths.

	Pointer movement anywhere over the plot selects the nearest point, so the hit
	target for any given day is the whole column around it and a reader never has
	to land on the line itself. That is strictly more forgiving than a fixed
	minimum width, and it means there is no gap between targets to fall into.

	Keyboard users get the same reading. Stepping a marker along an axis with the
	arrow keys is what `role="slider"` describes, so that is the role used: the
	value is the index of the day being read, and `aria-valuetext` carries the
	numbers a sighted reader would get from the tooltip.
-->
<script lang="ts" generics="T">
	import { getLayerCakeContext } from 'layercake';
	import type { Snippet } from 'svelte';
	import Tooltip from '../Tooltip.svelte';

	interface Props {
		/** Rows in the same order as the chart's x positions. */
		data: readonly T[];
		/** Tooltip body for the active row. */
		snippet: Snippet<[T]>;
		/** Spoken description of a row, for `aria-valuetext`. */
		describe?: (row: T) => string;
		/** Draw a vertical crosshair at the active row. */
		crosshair?: boolean;
		/** Accessible label for the reading control. */
		label?: string;
	}

	let {
		data,
		snippet,
		describe,
		crosshair = true,
		label = 'Chart values by day. Use the arrow keys to read each point.'
	}: Props = $props();

	const k = getLayerCakeContext();

	let active = $state<number | null>(null);

	const slots = $derived.by(() =>
		data.map((row, i) => ({ row, x: Number(k.xGet(row as never)), index: i }))
	);

	/** Index of the row nearest a pixel position. */
	function nearest(px: number): number | null {
		let best: number | null = null;
		let bestDistance = Number.POSITIVE_INFINITY;
		for (const slot of slots) {
			if (!Number.isFinite(slot.x)) continue;
			const distance = Math.abs(slot.x - px);
			if (distance < bestDistance) {
				bestDistance = distance;
				best = slot.index;
			}
		}
		return best;
	}

	function onpointermove(event: PointerEvent): void {
		const [px] = k.pointer(event);
		if (!Number.isFinite(px)) return;
		active = nearest(px);
	}

	function step(by: number): void {
		if (data.length === 0) return;
		const current = active ?? (by > 0 ? -1 : data.length);
		active = Math.max(0, Math.min(data.length - 1, current + by));
	}

	function onkeydown(event: KeyboardEvent): void {
		if (data.length === 0) return;
		switch (event.key) {
			case 'ArrowRight':
			case 'ArrowUp':
				event.preventDefault();
				step(1);
				break;
			case 'ArrowLeft':
			case 'ArrowDown':
				event.preventDefault();
				step(-1);
				break;
			case 'Home':
				event.preventDefault();
				active = 0;
				break;
			case 'End':
				event.preventDefault();
				active = data.length - 1;
				break;
			case 'Escape':
				active = null;
				break;
		}
	}

	const activeSlot = $derived(active === null ? null : (slots[active] ?? null));

	const valueText = $derived.by(() => {
		if (activeSlot === null) return undefined;
		return describe ? describe(activeSlot.row) : undefined;
	});
</script>

<div
	class="hover"
	role="slider"
	tabindex="0"
	aria-label={label}
	aria-valuemin={0}
	aria-valuemax={Math.max(0, data.length - 1)}
	aria-valuenow={active ?? 0}
	aria-valuetext={valueText}
	{onpointermove}
	onpointerleave={() => (active = null)}
	{onkeydown}
	onblur={() => (active = null)}
>
	{#if crosshair && activeSlot && Number.isFinite(activeSlot.x)}
		<div class="crosshair" style:left="{activeSlot.x}px" style:height="{k.height}px"></div>
	{/if}

	{#if activeSlot}
		<Tooltip x={activeSlot.x} y={0} width={k.width} height={k.height}>
			{@render snippet(activeSlot.row)}
		</Tooltip>
	{/if}
</div>

<style>
	.hover {
		position: absolute;
		inset: 0;
		cursor: crosshair;
	}

	.hover:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 1px;
	}

	.crosshair {
		position: absolute;
		top: 0;
		width: 1px;
		background: var(--ink-3);
		opacity: 0.7;
		pointer-events: none;
	}
</style>
