<!--
	@component
	A sortable table of model fingerprints.

	The "host effect" column is `d_provider / d_stable`: how many times further an
	answer moves when only the serving host changed. It is badged by severity, and
	it is an em dash whenever either side is missing, because a ratio against an
	unknown denominator is not a number.
-->
<script lang="ts">
	import Sparkline from '$lib/charts/Sparkline.svelte';
	import {
		EM_DASH,
		fmt,
		fmtCost,
		fmtInt,
		fmtMs,
		fmtPct,
		fmtRatio,
		fmtWords
	} from '$lib/data/format';
	import type { ModelFingerprint } from '$lib/data/types';

	interface Props {
		models: readonly ModelFingerprint[];
		/** Per-model daily stable series, for the inline sparklines. */
		series?: Record<string, (number | null)[]>;
		/** Models currently selected for the radar. */
		selected?: readonly string[];
		onToggle?: (modelId: string) => void;
	}

	let { models, series = {}, selected = [], onToggle }: Props = $props();

	type Key =
		| 'name'
		| 'n_answers'
		| 'mean_words'
		| 'refusal_rate'
		| 'hedge_rate'
		| 'reasoning_frac'
		| 'mean_duration_ms'
		| 'mean_cost'
		| 'd_stable'
		| 'host_effect'
		| 'repoints'
		| 'host_switches';

	let sortKey = $state<Key>('host_effect');
	let descending = $state(true);

	/** `d_provider / d_stable`, or null when either side is unmeasurable. */
	function hostEffect(model: ModelFingerprint): number | null {
		if (model.d_provider === null || model.d_stable === null || model.d_stable === 0) return null;
		return model.d_provider / model.d_stable;
	}

	function value(model: ModelFingerprint, key: Key): number | string | null {
		if (key === 'name') return model.name;
		if (key === 'host_effect') return hostEffect(model);
		return model[key];
	}

	const rows = $derived.by(() => {
		// Unmeasurable rows are held out of the sort entirely and appended, so
		// they stay last in both directions. Sorting them with the rest and then
		// reversing would float them to the top, which would read as "these rank
		// highest" when it means "these could not be measured".
		const measured: ModelFingerprint[] = [];
		const absent: ModelFingerprint[] = [];
		for (const model of models) {
			(value(model, sortKey) === null ? absent : measured).push(model);
		}

		measured.sort((a, b) => {
			const left = value(a, sortKey);
			const right = value(b, sortKey);
			if (typeof left === 'string' || typeof right === 'string') {
				return String(left).localeCompare(String(right));
			}
			return Number(left) - Number(right);
		});
		if (descending && sortKey !== 'name') measured.reverse();

		absent.sort((a, b) => a.name.localeCompare(b.name));
		return [...measured, ...absent];
	});

	function sortBy(key: Key): void {
		if (sortKey === key) descending = !descending;
		else {
			sortKey = key;
			descending = key !== 'name';
		}
	}

	function ariaSort(key: Key): 'ascending' | 'descending' | 'none' {
		if (sortKey !== key) return 'none';
		return descending ? 'descending' : 'ascending';
	}

	/** Thresholds are stated in the margin note, not inferred from colour. */
	function severity(ratio: number | null): '' | 'warn' | 'critical' {
		if (ratio === null) return '';
		if (ratio >= 2) return 'critical';
		if (ratio >= 1.25) return 'warn';
		return '';
	}

	const COLUMNS: { key: Key; label: string; help: string }[] = [
		{ key: 'name', label: 'Model', help: 'Model name' },
		{ key: 'n_answers', label: 'Answers', help: 'Archived answers analysed' },
		{ key: 'd_stable', label: 'Noise', help: 'Mean distance, build and host unchanged' },
		{ key: 'host_effect', label: 'Host effect', help: 'Host-switch distance ÷ noise' },
		{ key: 'host_switches', label: 'Switches', help: 'Days the serving host changed' },
		{ key: 'repoints', label: 'Rebuilds', help: 'Days the model build changed' },
		{ key: 'mean_words', label: 'Words', help: 'Mean answer length' },
		{ key: 'hedge_rate', label: 'Hedging', help: 'Hedge phrases per 250 words' },
		{ key: 'refusal_rate', label: 'Refusal', help: 'Share of answers that decline' },
		{
			key: 'reasoning_frac',
			label: 'Reasoning',
			help: 'Share of output tokens that are reasoning'
		},
		{ key: 'mean_duration_ms', label: 'Latency', help: 'Mean generation time' },
		{ key: 'mean_cost', label: 'Cost', help: 'Mean cost per answer' }
	];

	/** Shared sparkline ceiling so the column is comparable row to row. */
	const sparkMax = $derived.by(() => {
		const all = Object.values(series)
			.flat()
			.filter((v): v is number => v !== null && Number.isFinite(v));
		return all.length ? Math.max(...all) : null;
	});
</script>

<div class="wrap">
	<table>
		<caption class="sr-only"> Model fingerprints. Select a column heading to sort by it. </caption>
		<thead>
			<tr>
				{#if onToggle}
					<th scope="col" class="pick"><span class="sr-only">Compare</span></th>
				{/if}
				{#each COLUMNS as column (column.key)}
					<th scope="col" aria-sort={ariaSort(column.key)}>
						<button type="button" onclick={() => sortBy(column.key)} title={column.help}>
							{column.label}{#if sortKey === column.key}<span class="arrow" aria-hidden="true"
									>{descending ? '▾' : '▴'}</span
								>{/if}
						</button>
					</th>
				{/each}
				<th scope="col">Trend</th>
			</tr>
		</thead>
		<tbody>
			{#each rows as model (model.model_id)}
				{@const ratio = hostEffect(model)}
				{@const level = severity(ratio)}
				<tr>
					{#if onToggle}
						<td class="pick">
							<input
								type="checkbox"
								checked={selected.includes(model.model_id)}
								onchange={() => onToggle?.(model.model_id)}
								aria-label="Compare {model.name}"
							/>
						</td>
					{/if}
					<th scope="row" class="name" title={model.model_id}>
						{model.name}
						<span class="vendor">{model.vendor}</span>
					</th>
					<td>{fmtInt(model.n_answers)}</td>
					<td class:nil={model.d_stable === null}>{fmt(model.d_stable)}</td>
					<td>
						{#if ratio === null}
							<span class="nil">{EM_DASH}</span>
						{:else}
							<span class="badge {level}">{fmtRatio(ratio)}</span>
						{/if}
					</td>
					<td>{fmtInt(model.host_switches)}</td>
					<td>{fmtInt(model.repoints)}</td>
					<td>{fmtWords(model.mean_words)}</td>
					<td>{fmt(model.hedge_rate, 2)}</td>
					<td>{fmtPct(model.refusal_rate)}</td>
					<td>{fmtPct(model.reasoning_frac)}</td>
					<td>{fmtMs(model.mean_duration_ms)}</td>
					<td>{fmtCost(model.mean_cost)}</td>
					<td class="spark">
						{#if series[model.model_id]}
							<Sparkline
								values={series[model.model_id]}
								max={sparkMax}
								label="Daily stable-stratum distance for {model.name}"
							/>
						{:else}
							<span class="nil">{EM_DASH}</span>
						{/if}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.wrap {
		overflow-x: auto;
		max-height: 540px;
		overflow-y: auto;
	}

	thead th {
		z-index: 2;
	}

	thead button {
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		text-transform: inherit;
		letter-spacing: inherit;
		cursor: pointer;
		white-space: nowrap;
	}

	thead button:hover {
		color: var(--accent);
	}

	.arrow {
		margin-left: 0.2em;
		color: var(--accent);
	}

	.name {
		text-align: left;
		font-weight: 400;
		max-width: 190px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.vendor {
		display: block;
		color: var(--ink-3);
		font-size: 0.66rem;
	}

	.badge {
		display: inline-block;
		padding: 0.05em 0.4em;
		border-radius: 2px;
		border: 1px solid var(--rule-2);
	}

	.badge.warn {
		border-color: var(--warn);
		color: var(--warn);
	}

	.badge.critical {
		border-color: var(--critical);
		color: var(--critical);
	}

	.pick {
		width: 1.6rem;
		text-align: center;
	}

	td.spark {
		padding-right: 0.2em;
	}
</style>
