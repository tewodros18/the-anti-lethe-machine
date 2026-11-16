<!--
	@component
	The masthead: a mark and wordmark, the section index, the measure switch and
	the theme switch. Set in the monospace face like a directory listing, with
	the active section underlined in the accent.
-->
<script lang="ts">
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import ThemeToggle from './ThemeToggle.svelte';
	import { dataset } from '$lib/state/dataset.svelte';

	/** What each distance measure is, for the switcher's labels. */
	const MEASURES: Record<string, string> = {
		cosine_bow: 'word frequencies',
		jaccard_ngram: 'phrase overlap',
		ncd: 'compression',
		embedding: 'embedding',
		nli: 'contradiction'
	};

	function describe(name: string): string {
		const what = MEASURES[name];
		return what ? `${name} · ${what}` : name;
	}

	const LINKS = [
		{ href: '/', label: 'register' },
		{ href: '/models', label: 'models' },
		{ href: '/compare', label: 'compare' },
		{ href: '/method', label: 'method' }
	];

	/** Current route, normalised so `base` does not affect matching. */
	const current = $derived(page.url.pathname.replace(base, '') || '/');
</script>

<header class="masthead">
	<div class="inner">
		<a class="brand" href="{base}/">
			<span class="mark" aria-hidden="true"></span>
			<span class="wordmark">ANTI-LETHE</span>
		</a>

		<nav aria-label="Sections">
			<ul>
				{#each LINKS as link (link.href)}
					<li>
						<a
							href="{base}{link.href === '/' ? '/' : link.href}"
							aria-current={current === link.href ? 'page' : undefined}>{link.label}</a
						>
					</li>
				{/each}
			</ul>
		</nav>

		<div class="tools">
			{#if dataset.methods.length > 1}
				<div class="measure">
					<label for="measure">Measure</label>
					<select
						id="measure"
						value={dataset.method ?? ''}
						disabled={dataset.switching}
						onchange={(event) =>
							dataset.selectMethod((event.currentTarget as HTMLSelectElement).value)}
					>
						{#each dataset.methods as name (name)}
							<option value={name}>{describe(name)}</option>
						{/each}
					</select>
				</div>
			{/if}

			<ThemeToggle />
		</div>
	</div>
</header>

<style>
	.masthead {
		position: sticky;
		top: 0;
		z-index: 20;
		background: color-mix(in srgb, var(--paper) 90%, transparent);
		backdrop-filter: blur(8px);
	}

	.inner {
		max-width: var(--plate-max);
		margin: 0 auto;
		padding: 0.9rem var(--gutter) 0.7rem;
		display: flex;
		align-items: center;
		gap: 0.7rem 1.6rem;
		flex-wrap: wrap;
		border-bottom: 1px solid var(--rule-2);
	}

	.brand {
		text-decoration: none;
		color: inherit;
		display: flex;
		align-items: center;
		gap: 0.55em;
		min-width: 0;
	}

	.mark {
		width: 0.8em;
		height: 0.8em;
		border-radius: 50%;
		background: var(--accent);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
	}

	.wordmark {
		font-family: var(--font-mono);
		font-weight: 500;
		font-size: 0.86rem;
		letter-spacing: 0.12em;
	}

	nav {
		margin-left: auto;
	}

	nav ul {
		display: flex;
		gap: 0.2rem 1.1rem;
		list-style: none;
		margin: 0;
		padding: 0;
	}

	nav a {
		display: block;
		padding: 0.2em 0;
		color: var(--ink-2);
		text-decoration: none;
		font-family: var(--font-mono);
		font-size: 0.8rem;
		letter-spacing: 0.01em;
		border-bottom: 1.5px solid transparent;
	}

	nav a:hover {
		color: var(--ink);
	}

	nav a[aria-current='page'] {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}

	.tools {
		display: flex;
		align-items: center;
		gap: 0.8rem;
	}

	.measure {
		display: flex;
		align-items: center;
		gap: 0.4em;
	}

	.measure label {
		margin: 0;
	}

	.measure select {
		font-family: var(--font-mono);
		font-size: 0.72rem;
		padding: 0.25em 0.4em;
	}

	@media (max-width: 640px) {
		nav {
			margin-left: 0;
			order: 3;
			width: 100%;
		}

		nav ul {
			flex-wrap: wrap;
		}

		.tools {
			margin-left: auto;
		}
	}
</style>
