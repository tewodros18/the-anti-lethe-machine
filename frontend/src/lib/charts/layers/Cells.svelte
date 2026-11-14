<!--
	@component
	Heatmap cells: band scales on both axes, magnitude carried by opacity.

	A single hue with varying opacity, not a multi-hue ramp. A reader can rank
	one hue's opacity without a legend lookup, and it survives both themes and
	colour-vision deficiency without the mid-ramp ambiguity a rainbow has.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Props {
		/** Maps a row's value to 0–1 opacity. */
		opacity: (row: Record<string, unknown>) => number;
		fill?: string;
		/** Accessible text per cell, surfaced as a `<title>`. */
		title?: (row: Record<string, unknown>) => string;
		gap?: number;
		/** Called when a cell is hovered or focused; null on leave. */
		onhover?: (row: Record<string, unknown> | null) => void;
	}

	let { opacity, fill = 'var(--accent)', title, gap = 1, onhover }: Props = $props();

	const k = getLayerCakeContext();

	const cells = $derived.by(() => {
		const rows = (k.data ?? []) as Record<string, unknown>[];
		const xs = k.xScale as unknown as { bandwidth?: () => number };
		const ys = k.yScale as unknown as { bandwidth?: () => number };
		const bw = typeof xs.bandwidth === 'function' ? xs.bandwidth() : 10;
		const bh = typeof ys.bandwidth === 'function' ? ys.bandwidth() : 10;
		return rows.map((row) => ({
			row,
			x: Number(k.xGet(row)),
			y: Number(k.yGet(row)),
			w: Math.max(1, bw - gap),
			h: Math.max(1, bh - gap)
		}));
	});
</script>

<g class="cells">
	{#each cells as cell, i (i)}
		{#if Number.isFinite(cell.x) && Number.isFinite(cell.y)}
			<!-- Each cell is a labelled graphic in its own right, so it carries a
			     role and an accessible name rather than only a <title>. -->
			<rect
				x={cell.x}
				y={cell.y}
				width={cell.w}
				height={cell.h}
				{fill}
				fill-opacity={opacity(cell.row)}
				role="img"
				aria-label={title ? title(cell.row) : undefined}
				onpointerenter={() => onhover?.(cell.row)}
				onpointerleave={() => onhover?.(null)}
			>
				{#if title}<title>{title(cell.row)}</title>{/if}
			</rect>
		{/if}
	{/each}
</g>
