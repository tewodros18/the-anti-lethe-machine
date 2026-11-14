import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// GitHub Pages project sites are served from /<repo>, so every internal link
// and data fetch must go through `base`. The workflow sets BASE_PATH.
const base = process.env.BASE_PATH ?? '';

/** @type {import('@sveltejs/kit').Config} */
export default {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: '404.html',
			precompress: true
		}),
		paths: { base },
		prerender: { handleHttpError: 'fail' }
	}
};
