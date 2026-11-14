<!--
	@component
	Word-level diff rendering.

	Insertions and deletions carry a text decoration as well as a colour, so the
	distinction survives greyscale printing and colour-vision deficiency.
-->
<script lang="ts">
	import type { DiffToken } from '$lib/data/types';

	interface Props {
		tokens: readonly DiffToken[];
		/** Which side this pane is: deletions only, or insertions only. */
		side: 'before' | 'after';
	}

	let { tokens, side }: Props = $props();

	/** A pane shows its own changes plus the unchanged text around them. */
	const shown = $derived(
		tokens.filter(
			(token) =>
				token.op === 'equal' || (side === 'before' ? token.op === 'delete' : token.op === 'insert')
		)
	);
</script>

<p class="diff">
	{#each shown as token, i (i)}
		{#if token.op === 'equal'}<span>{token.text}</span>{:else if token.op === 'delete'}<del
				>{token.text}</del
			>{:else}<ins>{token.text}</ins>{/if}
	{/each}
</p>

<style>
	.diff {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: break-word;
		font-size: 0.85rem;
		line-height: 1.6;
		max-width: none;
	}

	del {
		background: color-mix(in srgb, var(--critical) 16%, transparent);
		color: var(--ink);
		text-decoration: line-through;
		text-decoration-thickness: 1px;
	}

	ins {
		background: color-mix(in srgb, var(--good) 18%, transparent);
		color: var(--ink);
		text-decoration: underline;
		text-decoration-thickness: 1px;
	}
</style>
