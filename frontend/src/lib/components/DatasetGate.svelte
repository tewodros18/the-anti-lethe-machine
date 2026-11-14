<!--
	@component
	Loading, error and ready states for the dataset.

	Acceptance criterion: deleting `static/data/` must show a designed state
	saying the dataset has not been built. Never a blank page, and never invented
	numbers standing in for missing ones. Every route renders its content through
	this gate so that promise holds on all of them.
-->
<script lang="ts">
	import { dataset } from '$lib/state/dataset.svelte';
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();
</script>

{#if dataset.error !== null}
	<section class="state error">
		<h1>The dataset has not been built</h1>
		<p class="detail">{dataset.error}</p>
		<p>
			This site reads a static JSON dataset produced by the pipeline. Nothing is computed in the
			browser, so with no dataset present there is nothing to show — and showing zeros here would be
			inventing findings rather than reporting them.
		</p>
		<h2>Build it</h2>
		<pre><code
				>uv venv --python 3.12
uv pip install -e 'backend[dev]'
antilethe ingest --questions is-climate-change-real
antilethe analyze
antilethe export --out frontend/static/data</code
			></pre>
		<p class="foot">
			The pipeline reads the Internet Archive's Ask Me Twice API and needs no key for a first run.
		</p>
	</section>
{:else if dataset.loading}
	<section class="state" aria-busy="true">
		<p class="loading">Loading the register…</p>
	</section>
{:else if dataset.index === null}
	<section class="state error">
		<h1>The dataset is empty</h1>
		<p>The dataset loaded but contains no measurements. Run the pipeline to populate it.</p>
	</section>
{:else}
	{@render children()}
{/if}

<style>
	.state {
		background: var(--plate);
		border: 1px solid var(--rule);
		border-radius: var(--radius);
		padding: 1.6rem var(--gutter);
		margin-top: 1rem;
	}

	.state.error {
		border-left: 3px solid var(--warn);
	}

	h1 {
		font-size: 1.5rem;
		margin-bottom: 0.5rem;
	}

	h2 {
		font-size: 0.74rem;
		font-family: var(--font-mono);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--ink-3);
		margin: 1.4rem 0 0.5rem;
	}

	.detail {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: var(--warn);
	}

	pre {
		background: var(--sunk);
		border: 1px solid var(--rule);
		border-radius: var(--radius);
		padding: 0.8rem;
		overflow-x: auto;
		margin: 0;
		font-size: 0.78rem;
		line-height: 1.6;
	}

	.foot {
		margin-top: 0.9rem;
		font-size: 0.8rem;
		color: var(--ink-3);
	}

	.loading {
		font-family: var(--font-mono);
		font-size: 0.82rem;
		color: var(--ink-3);
		margin: 0;
	}
</style>
