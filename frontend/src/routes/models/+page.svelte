<script lang="ts">
	import Heatmap from '$lib/charts/Heatmap.svelte';
	import Radar from '$lib/charts/Radar.svelte';
	import DataTable from '$lib/components/DataTable.svelte';
	import DatasetGate from '$lib/components/DatasetGate.svelte';
	import Plate from '$lib/components/Plate.svelte';
	import { fmt, fmtInt } from '$lib/data/format';
	import { dataset } from '$lib/state/dataset.svelte';

	const index = $derived(dataset.index);

	/** Unexplained first: a break with no event beside it is the finding. */
	const breaks = $derived.by(() =>
		[...(index?.changepoints ?? [])].sort((a, b) => {
			const ua = a.coincides_with === null ? 0 : 1;
			const ub = b.coincides_with === null ? 0 : 1;
			return ua - ub || a.day.localeCompare(b.day) || a.model_id.localeCompare(b.model_id);
		})
	);
	const unexplained = $derived(breaks.filter((b) => b.coincides_with === null).length);

	function explain(kind: 'version' | 'provider' | null): string {
		if (kind === 'version') return 'model rebuild';
		if (kind === 'provider') return 'host switch';
		return 'unexplained';
	}

	const MIN_SELECTED = 2;
	const MAX_SELECTED = 6;

	let picked = $state<string[]>([]);

	/**
	 * Default selection: the models with the most host switches, since those are
	 * the ones the register has something to say about. Chosen once, when the
	 * dataset first arrives, and then left under the reader's control.
	 */
	let seeded = false;
	$effect(() => {
		if (seeded || !index) return;
		seeded = true;
		picked = [...index.models]
			.sort((a, b) => b.host_switches - a.host_switches || b.n_answers - a.n_answers)
			.slice(0, 4)
			.map((model) => model.model_id);
	});

	function toggle(modelId: string): void {
		if (picked.includes(modelId)) {
			if (picked.length <= MIN_SELECTED) return;
			picked = picked.filter((id) => id !== modelId);
		} else {
			if (picked.length >= MAX_SELECTED) return;
			picked = [...picked, modelId];
		}
	}

	const shown = $derived.by(() =>
		(index?.models ?? []).filter((model) => picked.includes(model.model_id))
	);

	/** Per-model daily series for the table's sparklines. */
	const series = $derived.by(() => {
		const out: Record<string, (number | null)[]> = {};
		for (const model of index?.models ?? []) out[model.model_id] = model.daily;
		return out;
	});
</script>

<svelte:head>
	<title>Models — Anti-Lethe</title>
</svelte:head>

<DatasetGate>
	{#if index}
		<h1>Models<span class="stop">.</span></h1>
		<p class="lede">
			How each model behaves, and how much of its day-to-day movement is explained by the
			infrastructure underneath it rather than by the model.
		</p>

		<Plate
			title="Six-axis comparison"
			subtitle="{shown.length} of {index.models.length} models"
			note="Each axis is min–max scaled across the models currently selected, so every position is relative to this selection and changes when you add or remove a model. Nothing here is an absolute score, and two axes are inverted so that further out always means more of the thing named: stability is the inverse of measured drift, speed the inverse of latency. Use the table below to change the selection."
		>
			{#if shown.length >= MIN_SELECTED}
				<Radar models={shown} />
			{:else}
				<p class="hint">
					Select at least {MIN_SELECTED} models in the table below to compare them.
				</p>
			{/if}
		</Plate>

		<Plate
			title="Fingerprints"
			subtitle="Select up to {MAX_SELECTED} models to compare above"
			note="“Host effect” divides a model's mean distance across host switches by its mean distance when nothing changed. It is badged above 1.25× and again above 2×, and it is an em dash whenever either side is missing, because a ratio against an unknown denominator is not a number. Models served by a single first-party host have no host switches and therefore no host effect — that absence is a fact about routing, not a measurement of stability."
		>
			<DataTable models={index.models} {series} selected={picked} onToggle={toggle} />
		</Plate>

		<Plate
			title="When a model's level shifted"
			subtitle="{fmtInt(breaks.length)} change points, {fmtInt(unexplained)} with no known cause"
			note="Each row is a day on which a model's mean day-to-day distance settled at a new level, found by binary segmentation with a least-absolute-deviations cost and a BIC-style penalty, so a single anomalous day cannot create one. A break with a host switch or rebuild within a day of it is explained by that event. A break with neither is unexplained drift: the serving host and the build string both say nothing changed, and the answers say otherwise. Those rows are listed first. The series is at most one point per day, so a shift and its cause can be off by a day."
		>
			{#if breaks.length === 0}
				<p class="hint">
					No level shifts detected. Either the series are too short to split (ten days each side, at
					minimum) or no model's day-to-day distance settled at a new level.
				</p>
			{:else}
				<div class="table-wrap">
					<table>
						<caption class="sr-only">Detected change points by model and day</caption>
						<thead>
							<tr>
								<th scope="col">Day</th>
								<th scope="col">Model</th>
								<th scope="col">Before</th>
								<th scope="col">After</th>
								<th scope="col">Shift</th>
								<th scope="col">Days either side</th>
								<th scope="col">Coincides with</th>
							</tr>
						</thead>
						<tbody>
							{#each breaks as b (b.model_id + b.day)}
								<tr>
									<th scope="row">{b.day}</th>
									<td class="left">{b.model_id}</td>
									<td>{fmt(b.before_mean)}</td>
									<td>{fmt(b.after_mean)}</td>
									<td class:up={b.delta > 0} class:down={b.delta < 0}
										>{b.delta > 0 ? '+' : ''}{fmt(b.delta)}</td
									>
									<td>{fmtInt(b.n_before)} / {fmtInt(b.n_after)}</td>
									<td class="left">
										<span class="cause {b.coincides_with ?? 'none'}"
											>{explain(b.coincides_with)}</span
										>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Plate>

		<Plate
			title="Which questions are unsettled"
			subtitle="Mean distance per question and model, infrastructure held fixed"
			note="Every cell counts only pairs where the model build and the serving host were both unchanged, which is what separates an unsettled question from infrastructure churn. A dark row is a question models answer differently from one day to the next even when nothing underneath them moved — often a question about current events, where the honest answer genuinely changes. Rows are the most unsettled questions; the full set is in the dataset."
		>
			<Heatmap cells={index.cells} questions={index.questions} />
		</Plate>
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

	.hint {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: var(--ink-3);
		margin: 1.5rem 0;
	}

	.table-wrap {
		max-height: 440px;
		overflow: auto;
	}

	td.left {
		text-align: left;
	}

	td.up {
		color: var(--critical);
	}

	td.down {
		color: var(--good);
	}

	.cause {
		display: inline-block;
		padding: 0.05em 0.45em;
		border-radius: 2px;
		border: 1px solid var(--rule-2);
		font-size: 0.7rem;
	}

	.cause.none {
		border-color: var(--warn);
		color: var(--warn);
	}

	.cause.provider {
		border-color: var(--c5);
		color: var(--c5);
	}

	.cause.version {
		border-color: var(--c2);
		color: var(--c2);
	}
</style>
