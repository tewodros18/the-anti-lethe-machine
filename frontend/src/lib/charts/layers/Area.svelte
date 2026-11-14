<!--
	@component
	A constant-valued horizontal band spanning the plot width.

	This is the noise band. Both bounds are single numbers in data units, not
	series, because the noise floor is one distribution computed over the whole
	archive rather than a per-day figure. Drawn behind everything else, it reads
	as "the range where nothing happened".

	Renders nothing when either bound is null, which is what a noise floor with
	too few samples looks like.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Props {
		/** Lower bound in data units. */
		y0: number | null;
		/** Upper bound in data units. */
		y1: number | null;
		fill?: string;
		opacity?: number;
	}

	let { y0, y1, fill = 'var(--band)', opacity = 0.45 }: Props = $props();

	const k = getLayerCakeContext();

	const box = $derived.by(() => {
		if (y0 === null || y1 === null) return null;
		const a = Number(k.yScale(y0));
		const b = Number(k.yScale(y1));
		if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
		const top = Math.min(a, b);
		const height = Math.abs(a - b);
		return { top, height };
	});
</script>

{#if box}
	<rect
		class="band"
		x="0"
		y={box.top}
		width={k.width}
		height={box.height}
		{fill}
		{opacity}
		aria-hidden="true"
	/>
{/if}
