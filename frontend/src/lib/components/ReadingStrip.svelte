<!--
	@component
	The masthead readings: a strip of labelled figures between dashed rules.

	Each reading is one computed field from the dataset. A null reads as an em
	dash with a muted tone, never as zero. The lead readings are set large in
	the display face; the rest in tabular monospace.
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
		grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
		gap: 0;
		margin: 0;
		padding: 0;
		border-top: 1px dashed var(--rule-2);
		border-bottom: 1px dashed var(--rule-2);
	}

	.reading {
		padding: 1rem 1rem 0.9rem;
		min-width: 0;
		text-align: center;
		border-right: 1px dashed var(--rule-2);
	}

	.reading:last-child {
		border-right: 0;
	}

	dt {
		font-family: var(--font-mono);
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.14em;
		color: var(--ink-2);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	dd {
		margin: 0.35em 0 0;
		font-family: var(--font-mono);
		font-size: 1.3rem;
		font-variant-numeric: tabular-nums;
		color: var(--ink);
		line-height: 1.15;
	}

	.lead dd {
		font-family: var(--font-display);
		font-weight: 600;
		font-size: clamp(2rem, 1.4rem + 2vw, 2.9rem);
		letter-spacing: -0.02em;
		color: var(--accent);
	}

	.note {
		margin: 0.35em auto 0;
		font-family: var(--font-display);
		font-size: 0.86rem;
		color: var(--ink-2);
		max-width: 20ch;
		line-height: 1.3;
	}

	@media (max-width: 640px) {
		.reading {
			border-right: 0;
			border-bottom: 1px dashed var(--rule-2);
		}

		.reading:last-child {
			border-bottom: 0;
		}
	}
</style>
