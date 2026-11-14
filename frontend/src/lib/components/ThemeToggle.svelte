<!--
	@component
	Light / dark / system theme switch.

	Writes `data-theme` on the root element and remembers the choice. "System"
	removes the attribute so the media query takes over again. Storage access is
	wrapped because it throws in a private window with site data blocked.
-->
<script lang="ts">
	type Theme = 'light' | 'dark' | 'system';

	const KEY = 'antilethe-theme';

	function read(): Theme {
		try {
			const stored = localStorage.getItem(KEY);
			if (stored === 'light' || stored === 'dark') return stored;
		} catch {
			// Storage unavailable; fall back to following the system.
		}
		return 'system';
	}

	let theme = $state<Theme>('system');

	$effect(() => {
		theme = read();
	});

	function apply(next: Theme): void {
		theme = next;
		const root = document.documentElement;
		if (next === 'system') root.removeAttribute('data-theme');
		else root.setAttribute('data-theme', next);
		try {
			if (next === 'system') localStorage.removeItem(KEY);
			else localStorage.setItem(KEY, next);
		} catch {
			// The attribute is already set; persistence is a convenience only.
		}
	}

	const OPTIONS: { value: Theme; label: string }[] = [
		{ value: 'light', label: 'Light' },
		{ value: 'dark', label: 'Dark' },
		{ value: 'system', label: 'Auto' }
	];
</script>

<div class="toggle" role="group" aria-label="Colour theme">
	{#each OPTIONS as option (option.value)}
		<button
			class="btn"
			type="button"
			aria-pressed={theme === option.value}
			onclick={() => apply(option.value)}>{option.label}</button
		>
	{/each}
</div>

<style>
	.toggle {
		display: flex;
		gap: 0.25em;
	}

	.btn {
		font-size: 0.7rem;
		padding: 0.25em 0.5em;
	}
</style>
