<!--
	@component
	The fixed masthead: title, navigation, theme switch.
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
		{ href: '/', label: 'Register' },
		{ href: '/models', label: 'Models' },
		{ href: '/compare', label: 'Compare' },
		{ href: '/method', label: 'Method' }
	];

	/** Current route, normalised so `base` does not affect matching. */
	const current = $derived(page.url.pathname.replace(base, '') || '/');
</script>

<header class="masthead">
	<div class="inner">
		<a class="brand" href="{base}/">
			<span class="wordmark">Anti&#8209;Lethe</span>
			<span class="tagline">a drift register for model behaviour</span>
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
</header>

<style>
	.masthead {
		position: sticky;
		top: 0;
		z-index: 20;
		background: color-mix(in srgb, var(--paper) 92%, transparent);
		backdrop-filter: blur(8px);
		border-bottom: 1px solid var(--rule);
	}

	.inner {
		max-width: var(--plate-max);
		margin: 0 auto;
		padding: 0.55rem var(--gutter);
		display: flex;
		align-items: center;
		gap: 0.9rem 1.4rem;
		flex-wrap: wrap;
	}

	.brand {
		text-decoration: none;
		color: inherit;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.wordmark {
		font-family: var(--font-display);
		font-size: 1.14rem;
		font-weight: 600;
		letter-spacing: -0.015em;
		line-height: 1.1;
	}

	.tagline {
		font-family: var(--font-mono);
		font-size: 0.6rem;
		color: var(--ink-3);
		letter-spacing: 0.02em;
	}

	nav {
		margin-left: auto;
	}

	nav ul {
		display: flex;
		gap: 0.15rem;
		list-style: none;
		margin: 0;
		padding: 0;
	}

	nav a {
		display: block;
		padding: 0.3em 0.55em;
		color: var(--ink-2);
		text-decoration: none;
		font-family: var(--font-mono);
		font-size: 0.76rem;
		border-radius: var(--radius);
		border: 1px solid transparent;
	}

	nav a:hover {
		color: var(--ink);
		border-color: var(--rule-2);
	}

	nav a[aria-current='page'] {
		color: var(--ink);
		background: var(--plate);
		border-color: var(--rule-2);
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

	@media (max-width: 560px) {
		nav {
			margin-left: 0;
			order: 3;
			width: 100%;
		}

		nav ul {
			flex-wrap: wrap;
		}
	}
</style>
