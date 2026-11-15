<script lang="ts">
	import '../app.css';
	import Masthead from '$lib/components/Masthead.svelte';
	import { dataset } from '$lib/state/dataset.svelte';
	import type { Snippet } from 'svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();

	// One fetch for the whole session, started as soon as the app mounts.
	$effect(() => {
		void dataset.init();
	});
</script>

<a class="skip" href="#main">Skip to content</a>
<Masthead />

<main id="main">
	{@render children()}
</main>

<footer>
	<div class="inner">
		<p>
			Built from the Internet Archive's <em>Ask Me Twice</em> archive. Measurements are of archived text,
			not of models directly.
		</p>
		<p class="links">
			<a href="https://github.com/tewodros18/the-anti-lethe-machine">Source</a>
			<span aria-hidden="true">·</span>
			<a href="https://github.com/tewodros18/the-anti-lethe-machine/releases/tag/archive">Archive</a
			>
			<span aria-hidden="true">·</span>
			<a href="https://github.com/tewodros18/the-anti-lethe-machine/blob/main/LICENSE">MIT</a>
		</p>
	</div>
</footer>

<style>
	.skip {
		position: absolute;
		left: -9999px;
		top: 0;
		z-index: 100;
		background: var(--plate);
		padding: 0.5em 0.8em;
		border: 1px solid var(--accent);
	}

	.skip:focus {
		left: 0.5rem;
		top: 0.5rem;
	}

	main {
		max-width: var(--plate-max);
		margin: 0 auto;
		padding: 1.4rem var(--gutter) 3rem;
	}

	footer {
		border-top: 1px dashed var(--rule-2);
		margin-top: 2rem;
	}

	footer .inner {
		max-width: var(--plate-max);
		margin: 0 auto;
		padding: 1.2rem var(--gutter) 2.4rem;
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		flex-wrap: wrap;
	}

	footer p {
		margin: 0;
		font-size: 0.76rem;
		color: var(--ink-3);
		max-width: 60ch;
	}

	.links {
		font-family: var(--font-mono);
		display: flex;
		gap: 0.5em;
	}
</style>
