<!--
	@component
	A chart section: a display-face title over a dashed rule, the chart, and a
	margin note.

	The margin note is required, not optional. Every chart in this project needs a
	sentence saying what it does *not* show, because the whole point is that one
	number here would be misleading.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		/** Short line under the title. */
		subtitle?: string;
		/** What this chart does and does not show. */
		note: string;
		children: Snippet;
		/** Optional controls rendered in the header. */
		controls?: Snippet;
	}

	let { title, subtitle, note, children, controls }: Props = $props();
</script>

<section class="plate">
	<header>
		<div class="titles">
			<h2>{title}</h2>
			{#if subtitle}<p class="subtitle">{subtitle}</p>{/if}
		</div>
		{#if controls}
			<div class="controls">{@render controls()}</div>
		{/if}
	</header>

	<div class="body">
		{@render children()}
	</div>

	<p class="note">{note}</p>
</section>

<style>
	.plate {
		padding: 1.6rem 0 1.2rem;
		margin-bottom: 0.6rem;
		border-top: 1px dashed var(--rule-2);
	}

	header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 1em;
		flex-wrap: wrap;
		margin-bottom: 1.1rem;
	}

	.titles {
		min-width: 0;
	}

	h2 {
		font-size: clamp(1.4rem, 1.1rem + 1vw, 1.85rem);
		font-weight: 500;
	}

	.subtitle {
		margin: 0.25em 0 0;
		color: var(--ink-2);
		font-family: var(--font-display);
		font-size: 1rem;
	}

	.controls {
		display: flex;
		gap: 0.5em;
		flex-wrap: wrap;
		align-items: flex-end;
	}

	.body {
		min-width: 0;
		background: var(--plate);
		border: 1px solid var(--rule);
		border-radius: var(--radius);
		padding: 1rem var(--gutter);
	}

	.note {
		margin: 0.8rem 0 0;
		color: var(--ink-3);
		font-size: 0.78rem;
		line-height: 1.5;
		max-width: 80ch;
	}
</style>
