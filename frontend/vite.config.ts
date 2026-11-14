import { sveltekit } from '@sveltejs/kit/vite';
// `vitest/config` rather than `vite`, so the `test` block is a known property.
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
	// Under Vitest, resolve Svelte's browser build: its server build has no
	// `mount`, so component tests cannot render without this.
	resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
	test: {
		include: ['src/tests/**/*.test.ts'],
		// Component tests need a DOM; the pure-function tests do not care.
		environment: 'happy-dom'
	}
});
