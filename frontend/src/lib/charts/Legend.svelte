<!--
	@component
	Series legend. Shown whenever a chart carries two or more series, because
	identity is never left to colour alone.
-->
<script lang="ts">
	interface Entry {
		label: string;
		color: string;
		/** `line` draws a rule, `dash` a dashed rule, `swatch` a filled block. */
		shape?: 'line' | 'dash' | 'swatch';
		/** Appended in muted type, e.g. a sample size. */
		note?: string;
	}

	interface Props {
		entries: readonly Entry[];
	}

	let { entries }: Props = $props();
</script>

<ul class="legend">
	{#each entries as entry (entry.label)}
		<li>
			<span
				class="mark"
				class:dash={entry.shape === 'dash'}
				class:swatch={entry.shape === 'swatch'}
				style:--mark-color={entry.color}
				aria-hidden="true"
			></span>
			<span class="label">{entry.label}</span>
			{#if entry.note}<span class="note">{entry.note}</span>{/if}
		</li>
	{/each}
</ul>

<style>
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4em 1.1em;
		list-style: none;
		margin: 0 0 0.6em;
		padding: 0;
		font-family: var(--font-mono);
		font-size: 0.72rem;
	}

	li {
		display: flex;
		align-items: center;
		gap: 0.4em;
	}

	.mark {
		display: inline-block;
		width: 16px;
		height: 0;
		border-top: 2.5px solid var(--mark-color);
		flex: none;
	}

	.mark.dash {
		border-top-style: dashed;
	}

	.mark.swatch {
		height: 10px;
		border: 0;
		background: var(--mark-color);
		border-radius: 1px;
	}

	.label {
		color: var(--ink-2);
	}

	.note {
		color: var(--ink-3);
	}
</style>
