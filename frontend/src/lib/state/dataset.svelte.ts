/**
 * Dataset state, in runes.
 *
 * No `writable`, no `$store` syntax. Components read `dataset.index` directly
 * and Svelte 5 tracks the dependency.
 *
 * A build can carry the register under several distance measures. `index` is
 * whichever one is selected; `methods` lists what the build exported, and
 * `selectMethod` swaps the whole dataset so every chart re-renders under the
 * new measure. Snapshot shards are shared: which days they hold depends on the
 * build and host strings, not on any distance.
 */

import { DatasetError, loadIndex, loadManifest, loadMethodIndex, loadShard } from '$lib/data/load';
import type { Index, Manifest, SnapshotShard } from '$lib/data/types';

class DatasetState {
	index = $state<Index | null>(null);
	manifest = $state<Manifest | null>(null);
	loading = $state(true);
	error = $state<string | null>(null);
	shards = $state<Record<string, SnapshotShard>>({});

	/** Per-shard load errors, so one bad shard cannot blank the page. */
	shardErrors = $state<Record<string, string>>({});

	/** The measure currently shown; follows `index.method.name`. */
	readonly method = $derived(this.index?.method.name ?? null);

	/** Measures this build exported a full index for. */
	readonly methods = $derived.by(() => {
		const exported = this.manifest?.methods_exported ?? [];
		const current = this.index?.method.name;
		return current && !exported.includes(current) ? [current, ...exported] : exported;
	});

	/** True while a different measure is being fetched. */
	switching = $state(false);

	readonly ready = $derived(this.index !== null && !this.loading);

	#started = false;
	#pending = new Map<string, Promise<SnapshotShard>>();
	#indexes = new Map<string, Index>();

	/** Fetch the index and manifest once. Safe to call from several components. */
	async init(): Promise<void> {
		if (this.#started) return;
		this.#started = true;
		this.loading = true;
		this.error = null;
		try {
			// The manifest is provenance only; a missing one must not blank the
			// register, so it is loaded separately and allowed to fail quietly.
			const index = await loadIndex();
			this.index = index;
			this.#indexes.set(index.method.name, index);
			try {
				this.manifest = await loadManifest();
			} catch {
				this.manifest = null;
			}
		} catch (error) {
			this.index = null;
			this.error =
				error instanceof DatasetError
					? error.message
					: `The dataset could not be loaded: ${String(error)}`;
			// Allow a later retry after a transient failure.
			this.#started = false;
		} finally {
			this.loading = false;
		}
	}

	/** Show the register under a different measure. Memoised per method. */
	async selectMethod(name: string): Promise<void> {
		if (name === this.method) return;
		const cached = this.#indexes.get(name);
		if (cached) {
			this.index = cached;
			return;
		}
		this.switching = true;
		try {
			const index = await loadMethodIndex(name);
			this.#indexes.set(name, index);
			this.index = index;
		} catch (error) {
			// The current measure stays on screen; the failure is reported, not
			// substituted with an empty dataset.
			this.error = error instanceof DatasetError ? error.message : `Could not load "${name}".`;
		} finally {
			this.switching = false;
		}
	}

	/** Fetch one question's snapshot shard, memoised. */
	async shard(questionSlug: string): Promise<SnapshotShard> {
		const cached = this.shards[questionSlug];
		if (cached) return cached;

		const inflight = this.#pending.get(questionSlug);
		if (inflight) return inflight;

		const request = loadShard(questionSlug)
			.then((shard) => {
				this.shards = { ...this.shards, [questionSlug]: shard };
				const { [questionSlug]: _removed, ...rest } = this.shardErrors;
				void _removed;
				this.shardErrors = rest;
				return shard;
			})
			.catch((error: unknown) => {
				const message =
					error instanceof DatasetError ? error.message : `Could not load "${questionSlug}".`;
				this.shardErrors = { ...this.shardErrors, [questionSlug]: message };
				throw error;
			})
			.finally(() => {
				this.#pending.delete(questionSlug);
			});

		this.#pending.set(questionSlug, request);
		return request;
	}

	/** Question slugs, ordered by their prose. */
	readonly questionSlugs = $derived.by(() => {
		const questions = this.index?.questions ?? {};
		return Object.keys(questions).sort((a, b) =>
			(questions[a]?.text ?? a).localeCompare(questions[b]?.text ?? b)
		);
	});

	/** Model ids, ordered by id. */
	readonly modelIds = $derived.by(() =>
		(this.index?.models ?? []).map((m) => m.model_id).sort((a, b) => a.localeCompare(b))
	);

	/** Fingerprint lookup by model id. */
	readonly modelById = $derived.by(() => {
		const out = new Map<string, Index['models'][number]>();
		for (const model of this.index?.models ?? []) out.set(model.model_id, model);
		return out;
	});
}

export const dataset = new DatasetState();
