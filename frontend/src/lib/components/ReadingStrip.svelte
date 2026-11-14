<!--
	@component
	The masthead readings: a row of labelled scalars.

	Each reading is one computed field from the dataset. A null reads as an em
	dash with a muted tone, never as zero.
-->
<script lang="ts">
	import { EM_DASH } from '$lib/data/format';

	interface Reading {
		label: string;
		value: string;
		/** Small line under the value, e.g. a sample size. */
		note?: string;
		/** Render large, for the headline figures. */
		lead?: boolean;
	}

	interface Props {
		readings: readonly Reading[];
	}

	let { readings }: Props = $props();
</script>

<dl class="strip">
	{#each readings as reading (reading.label)}
		<div class="reading" class:lead={reading.lead}>
			<dt>{reading.label}</dt>
			<dd class:nil={reading.value === EM_DASH}>{reading.value}</dd>
			{#if reading.note}<p class="note">{reading.note}</p>{/if}
		</div>
	{/each}
</dl>

<style>
	.strip {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
		gap: 0.1rem 1.4rem;
		margin: 0;
		padding: 0;
	}

	.reading {
		padding: 0.45rem 0;
		min-width: 0;
	}

	dt {
		font-family: var(--font-mono);
		font-size: 0.64rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--ink-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	dd {
		margin: 0.12em 0 0;
		font-family: var(--font-mono);
		font-size: 1.14rem;
		font-variant-numeric: tabular-nums;
		color: var(--ink);
		line-height: 1.2;
	}

	.lead dd {
		font-size: 1.7rem;
		color: var(--accent);
	}

	.note {
		margin: 0.1em 0 0;
		font-family: var(--font-mono);
		font-size: 0.62rem;
		color: var(--ink-3);
		max-width: none;
	}
</style>
