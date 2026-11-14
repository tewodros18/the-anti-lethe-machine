<!--
	@component
	A horizontal reference line at one data value, with an optional label.

	Renders nothing when the value is null, so a missing median leaves no line
	rather than a line at zero.
-->
<script lang="ts">
	import { getLayerCakeContext } from 'layercake';

	interface Props {
		value: number | null;
		stroke?: string;
		dash?: string | null;
		width?: number;
		/** Short text drawn at the right end of the rule. */
		label?: string | null;
	}

	let { value, stroke = 'var(--ink-3)', dash = '3 3', width = 1, label = null }: Props = $props();

	const k = getLayerCakeContext();
	const y = $derived(value === null ? null : Number(k.yScale(value)));
</script>

{#if y !== null && Number.isFinite(y)}
	<g transform="translate(0,{y})" aria-hidden="true">
		<line x1="0" x2={k.width} {stroke} stroke-width={width} stroke-dasharray={dash} />
		{#if label}
			<text x={k.width} y="-4" class="label">{label}</text>
		{/if}
	</g>
{/if}

<style>
	.label {
		fill: var(--ink-3);
		font-family: var(--font-mono);
		font-size: 9.5px;
		text-anchor: end;
	}
</style>
