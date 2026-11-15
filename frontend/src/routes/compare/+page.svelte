<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import Trajectory from '$lib/charts/Trajectory.svelte';
	import StanceTimeline from '$lib/charts/StanceTimeline.svelte';
	import DatasetGate from '$lib/components/DatasetGate.svelte';
	import Plate from '$lib/components/Plate.svelte';
	import SnapshotDiff from '$lib/components/SnapshotDiff.svelte';
	import { dataset } from '$lib/state/dataset.svelte';
	import type { LedgerDay, Snapshot, SnapshotShard } from '$lib/data/types';

	const index = $derived(dataset.index);

	let question = $state('');
	let model = $state('');
	let dayA = $state('');
	let dayB = $state('');

	let shard = $state<SnapshotShard | null>(null);
	let shardError = $state<string | null>(null);
	let loadingShard = $state(false);

	/**
	 * State lives in a single `#` token: `question|model|dayA|dayB`.
	 *
	 * A static host serves one HTML file per route, so a query string would be
	 * dropped by the prerendered fallback on a cold load. A hash survives, and
	 * `replaceState` updates it without a navigation.
	 */
	function readToken(): string[] {
		const raw = page.url.hash.replace(/^#/, '');
		return raw ? raw.split('|').map(decodeURIComponent) : [];
	}

	function writeToken(): void {
		const token = [question, model, dayA, dayB].map(encodeURIComponent).join('|');
		try {
			replaceState(`#${token}`, page.state);
		} catch {
			// Before hydration finishes `replaceState` is unavailable; the
			// selection still works, it just is not linkable until then.
		}
	}

	/** Seed the selection from the URL, else from the first available option. */
	let seeded = false;
	$effect(() => {
		if (seeded || !index) return;
		seeded = true;

		const [tQuestion, tModel, tA, tB] = readToken();
		const slugs = Object.keys(index.snapshot_days);
		question = tQuestion && slugs.includes(tQuestion) ? tQuestion : (slugs[0] ?? '');
		const models = index.models.map((m) => m.model_id);
		model = tModel && models.includes(tModel) ? tModel : (models[0] ?? '');
		dayA = tA ?? '';
		dayB = tB ?? '';
	});

	/** Days the export kept for the selected question. */
	const days = $derived(question ? (index?.snapshot_days[question] ?? []) : []);

	/** The hash chain keyed by day, for the roots shown beside each snapshot. */
	const ledgerByDay = $derived.by<Record<string, LedgerDay>>(() => {
		const out: Record<string, LedgerDay> = {};
		for (const entry of dataset.manifest?.ledger ?? []) out[entry.day] = entry;
		return out;
	});

	/** Load the shard whenever the question changes. */
	$effect(() => {
		if (!question) return;
		const slug = question;
		loadingShard = true;
		shardError = null;
		dataset
			.shard(slug)
			.then((loaded) => {
				if (question === slug) shard = loaded;
			})
			.catch(() => {
				if (question === slug) {
					shard = null;
					shardError = dataset.shardErrors[slug] ?? `Could not load snapshots for "${slug}".`;
				}
			})
			.finally(() => {
				if (question === slug) loadingShard = false;
			});
	});

	/** Days this model actually has snapshots for, within the kept days. */
	const modelDays = $derived.by(() => {
		if (!shard || !model) return [];
		return Object.keys(shard.models[model] ?? {}).sort();
	});

	/** Whether any kept snapshot of this model carries the stance probe. */
	const hasStance = $derived.by(() => {
		if (!shard || !model) return false;
		return Object.values(shard.models[model] ?? {}).some(
			(snap) => snap.features.stance_yes !== undefined
		);
	});

	/**
	 * Keep the two day selections valid as the question or model changes. Prefer
	 * a pair that straddles an event, since that is the comparison worth seeing.
	 */
	$effect(() => {
		const available = modelDays;
		if (available.length === 0) return;
		if (!available.includes(dayA) || !available.includes(dayB) || dayA === dayB) {
			const pair = interestingPair(available);
			dayA = pair[0];
			dayB = pair[1];
		}
	});

	/** The first adjacent pair whose build or host differs, else the last two days. */
	function interestingPair(available: string[]): [string, string] {
		if (!shard || !model) return [available[0], available[available.length - 1]];
		const snaps = shard.models[model] ?? {};
		for (let i = 1; i < available.length; i += 1) {
			const before = snaps[available[i - 1]];
			const after = snaps[available[i]];
			if (!before || !after) continue;
			if (
				before.canonical_slug !== after.canonical_slug ||
				before.serving_host !== after.serving_host
			) {
				return [available[i - 1], available[i]];
			}
		}
		return [available[0], available[available.length - 1]];
	}

	$effect(() => {
		if (question && model && dayA && dayB) writeToken();
	});

	const snapA = $derived<Snapshot | null>(shard?.models[model]?.[dayA] ?? null);
	const snapB = $derived<Snapshot | null>(shard?.models[model]?.[dayB] ?? null);

	const questionText = $derived(
		shard?.question_text ?? index?.questions[question]?.text ?? question
	);

	/** Models that have any snapshot in the loaded shard. */
	const availableModels = $derived.by(() => {
		if (!shard) return index?.models.map((m) => m.model_id) ?? [];
		return Object.keys(shard.models).sort();
	});
</script>

<svelte:head>
	<title>Compare — Anti-Lethe</title>
</svelte:head>

<DatasetGate>
	{#if index}
		<h1>Compare two days</h1>
		<p class="lede">
			The same question, the same model, two different days. What the differences mean depends
			entirely on whether the build and the host stayed the same, so that verdict is stated before
			the text.
		</p>

		<Plate
			title="Snapshot diff"
			subtitle={questionText}
			note="Only the days the exporter kept are listed: the first and last day, every seventh day, and both sides of every host switch and rebuild. Answers are shown to 4000 characters while the SHA-256 is of the complete text, so a truncated pane can still be checked against the ledger. The highlighted words are a direct word-level diff computed in the browser, not the dataset's distance measure."
		>
			{#snippet controls()}
				<div class="picker">
					<label for="q">Question</label>
					<select id="q" bind:value={question}>
						{#each Object.keys(index.snapshot_days) as slug (slug)}
							<option value={slug}>{index.questions[slug]?.text ?? slug}</option>
						{/each}
					</select>
				</div>
				<div class="picker">
					<label for="m">Model</label>
					<select id="m" bind:value={model}>
						{#each availableModels as id (id)}
							<option value={id}>{id}</option>
						{/each}
					</select>
				</div>
				<div class="picker narrow">
					<label for="da">Day A</label>
					<select id="da" bind:value={dayA}>
						{#each modelDays as day (day)}
							<option value={day}>{day}</option>
						{/each}
					</select>
				</div>
				<div class="picker narrow">
					<label for="db">Day B</label>
					<select id="db" bind:value={dayB}>
						{#each modelDays as day (day)}
							<option value={day}>{day}</option>
						{/each}
					</select>
				</div>
			{/snippet}

			{#if shardError}
				<p class="problem">{shardError}</p>
			{:else if loadingShard && !shard}
				<p class="hint">Loading snapshots…</p>
			{:else if modelDays.length === 0}
				<p class="hint">
					No snapshots were kept for this model on this question. Pick another model.
				</p>
			{:else}
				<SnapshotDiff
					{questionText}
					modelId={model}
					{dayA}
					{dayB}
					a={snapA}
					b={snapB}
					ledger={ledgerByDay}
				/>
			{/if}
		</Plate>

		{#if shard && modelDays.length > 0 && hasStance}
			<Plate
				title="Where the model stands"
				subtitle="This model's position on this question, day by day, under the stance probe"
				note="Each archived answer is scored by the entailment model against three fixed hypotheses: that the answer says yes, that it says no, and that it declines to take a position. The three lines are those probabilities on the days the export kept; a gap is a day not kept, not an answer that was missing. The ringed points are the two days compared above. A rewording leaves the lines where they were; a reversal swaps the yes and no lines. This is drawn only when the build ran the stance_nli method, and the checkpoint it ran is named on the method page."
			>
				<StanceTimeline snapshots={shard.models[model] ?? {}} {dayA} {dayB} />
			</Plate>
		{/if}

		{#if shard && modelDays.length > 0}
			<Plate
				title="Where the answers sit"
				subtitle="Every model's answers to this question, in its embedding plane"
				note="Each point is one archived answer, placed by the first two principal components of its sentence embedding, computed over every answer to this question. Distances within the plane are comparable; the axes themselves are not, and are not shared with any other question. The highlighted model's answers are joined in day order, and the two days compared above are ringed. A pair far apart here moved in meaning under the embedding model's judgement, whatever the word diff looks like; a pair close together is a rewording. This is drawn only when the build ran the embedding_map method."
			>
				<Trajectory models={shard.models} focus={model} {dayA} {dayB} />
			</Plate>
		{/if}

		{#if days.length > 0}
			<p class="foot">
				{days.length} day{days.length === 1 ? '' : 's'} kept for this question.
			</p>
		{/if}
	{/if}
</DatasetGate>

<style>
	h1 {
		margin-bottom: 0.4rem;
	}

	.lede {
		color: var(--ink-2);
		margin-bottom: 1.4rem;
	}

	.picker {
		min-width: 0;
		max-width: 260px;
	}

	.picker.narrow {
		max-width: 130px;
	}

	.picker select {
		width: 100%;
	}

	.hint,
	.problem {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		margin: 1.4rem 0;
	}

	.hint {
		color: var(--ink-3);
	}

	.problem {
		color: var(--warn);
	}

	.foot {
		font-family: var(--font-mono);
		font-size: 0.72rem;
		color: var(--ink-3);
	}
</style>
