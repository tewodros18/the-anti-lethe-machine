<script lang="ts">
	import DatasetGate from '$lib/components/DatasetGate.svelte';
	import Plate from '$lib/components/Plate.svelte';
	import { EM_DASH, fmt, fmtBytes, fmtInt, fmtTimestamp, longDay } from '$lib/data/format';
	import { dataset } from '$lib/state/dataset.svelte';

	const index = $derived(dataset.index);
	const manifest = $derived(dataset.manifest);

	/**
	 * The six limitations. Written out as content rather than generated, because
	 * each one is a claim about what this project cannot tell you and none of
	 * them follows from a number in the dataset.
	 */
	const LIMITATIONS: { title: string; body: string }[] = [
		{
			title: 'One sample per day',
			body:
				'The archive records a single answer per question per model per day. A model that answers ' +
				'differently on consecutive attempts within one day is indistinguishable here from one ' +
				'that drifted overnight. Every distance reported is therefore a lower bound on how much ' +
				'variation the model is capable of, not a measurement of change over time.'
		},
		{
			title: 'Routed through OpenRouter, not direct',
			body:
				'Answers are generated through OpenRouter rather than by calling each vendor directly. ' +
				'What is observed is a model as served by whichever host OpenRouter selected, including ' +
				'that host’s quantisation, context handling and serving stack. A vendor’s own ' +
				'API might answer differently on the same day with the same weights.'
		},
		{
			title: 'Word frequencies, not meaning',
			body:
				'The default distance counts how often each word appears and compares those counts. It ' +
				'cannot distinguish a reversal from a rewording: “X is safe” and “X is ' +
				'not safe” score as nearly identical. It is the default because any reader can ' +
				'verify a number by hand. The refusal and stance markers sit beside it for exactly this ' +
				'reason, and the optional entailment method is the one that actually detects reversals. ' +
				'When a build exports them, the masthead switches the whole register to the embedding ' +
				'and entailment measures; the limitation then changes shape rather than going away.'
		},
		{
			title: 'Sampling parameters are unrecorded',
			body:
				'Temperature, top-p, seed and system prompt are not captured in the archive. A change in ' +
				'any of them would appear in this register as model drift, and there is no way from here ' +
				'to rule that out. The stable stratum absorbs it into what is reported as noise.'
		},
		{
			title: 'Hashes prove custody, not origin',
			body:
				'The ledger proves that a record has not been altered since it was fetched. It does not ' +
				'and cannot prove that a given model produced it. Provenance rests on the Internet ' +
				'Archive’s operation of the upstream archive, not on cryptography.'
		},
		{
			title: 'The probe set is public, and therefore contaminable',
			body:
				'The questions are published and stable, so they can be trained on, cached, or special-' +
				'cased. A model that became more consistent on these specific questions has not ' +
				'necessarily become more consistent in general, and this register cannot tell the ' +
				'difference between the two.'
		}
	];
</script>

<svelte:head>
	<title>Method — Anti-Lethe</title>
</svelte:head>

<DatasetGate>
	{#if index}
		<h1>Method</h1>
		<p class="lede">What is measured, how, and what the measurement cannot tell you.</p>

		<Plate
			title="The three strata"
			note="This classification is the whole method. Two of the three categories are decided by exact string comparison and carry no statistical uncertainty; only the size of a difference within a category is a measurement."
		>
			<dl class="strata">
				<div>
					<dt><span class="chip c1"></span>stable</dt>
					<dd>
						The canonical build string and the serving host are both identical between the two days.
						Whatever differs is sampling noise. This is the denominator for everything else: the
						baseline that says how much an answer moves when nothing changed.
					</dd>
				</div>
				<div>
					<dt><span class="chip c5"></span>provider</dt>
					<dd>
						The build string is identical but the serving host differs. The archive routes through
						OpenRouter, so an open-weight model can be served by Novita one day and DeepInfra the
						next. Quantisation and serving stack change. The model does not.
					</dd>
				</div>
				<div>
					<dt><span class="chip c2"></span>version</dt>
					<dd>
						The build string differs: the vendor repointed a model-id alias at a new dated build.
						This is the only category where a difference is unambiguously the model changing. It is
						detected by exact string comparison and takes precedence when the host changed too,
						because a rebuild is the stronger claim and the two cannot be separated.
					</dd>
				</div>
			</dl>
		</Plate>

		<Plate
			title="Installed methods"
			subtitle="Measurements in this dataset were produced by {index.method.name} v{index.method
				.version}"
			note="Every aggregate carries the name and version of the method that produced it, so a dataset computed one way can never be silently compared against one computed another way. A method whose optional dependency is absent is excluded from a build rather than failing it."
		>
			{#if manifest}
				<table>
					<caption class="sr-only">Analysis methods present in this build</caption>
					<thead>
						<tr>
							<th scope="col">Method</th>
							<th scope="col">Kind</th>
							<th scope="col">Version</th>
							<th scope="col">Checkpoint</th>
							<th scope="col">Shown now</th>
						</tr>
					</thead>
					<tbody>
						{#each manifest.methods_installed as method (method.name)}
							<tr>
								<th scope="row">{method.name}</th>
								<td class="left">{method.kind}</td>
								<td>{method.version}</td>
								<td class="left mono" class:nil={method.model === null}
									>{method.model ?? EM_DASH}</td
								>
								<td>{method.name === index.method.name ? 'yes' : '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<p class="hint">
					The build manifest is not available, so the installed method list cannot be shown.
				</p>
			{/if}
		</Plate>

		<Plate
			title="Model rebuilds"
			subtitle="{fmtInt(index.version_events.length)} observed in this window"
			note="Each row is one day on which a model-id alias began resolving to a different dated build. A rebuild affects every question at once, so it is counted once per model per day no matter how many questions observed it."
		>
			{#if index.version_events.length === 0}
				<p class="none">
					No model rebuilds occurred between {longDay(index.span.first)} and
					{longDay(index.span.last)}. Every model-id alias resolved to the same dated build on every
					day in this window.
				</p>
				<p class="none-note">
					This is a finding, not a gap. It means the rebuild column of this register has no
					observations yet, and so the rebuild-versus-noise ratio is reported as an em dash rather
					than as a number. A repoint during a later run will populate it.
				</p>
			{:else}
				<div class="table-wrap">
					<table>
						<caption class="sr-only">Model build changes by day</caption>
						<thead>
							<tr>
								<th scope="col">Day</th>
								<th scope="col">Model</th>
								<th scope="col">From</th>
								<th scope="col">To</th>
							</tr>
						</thead>
						<tbody>
							{#each index.version_events as event (event.day + event.model_id)}
								<tr>
									<th scope="row">{event.day}</th>
									<td class="left">{event.model_id}</td>
									<td class="left mono" class:nil={!event.from_canonical}
										>{event.from_canonical ?? EM_DASH}</td
									>
									<td class="left mono" class:nil={!event.to_canonical}
										>{event.to_canonical ?? EM_DASH}</td
									>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</Plate>

		<Plate
			title="Ledger"
			note="The ledger is a SHA-256 Merkle tree over each day's answer hashes, with every day chained to the one before it. `antilethe verify` recomputes every root from the rows now in the database and exits non-zero on any mismatch."
		>
			<blockquote>
				This ledger proves that a record has not been altered since it was fetched. It does not and
				cannot prove that a given model produced it. Provenance rests on the Internet Archive's
				operation of the upstream archive, not on cryptography.
			</blockquote>

			{#if manifest?.ledger_head}
				<dl class="facts">
					<div>
						<dt>Head day</dt>
						<dd>{manifest.ledger_head.day}</dd>
					</div>
					<div>
						<dt>Rows archived</dt>
						<dd>{fmtInt(manifest.row_count)}</dd>
					</div>
					<div class="full">
						<dt>Head Merkle root</dt>
						<dd class="hash">{manifest.ledger_head.merkle_root}</dd>
					</div>
				</dl>
			{:else}
				<p class="hint">No ledger head is recorded in this build.</p>
			{/if}
		</Plate>

		<Plate
			title="Limitations"
			note="These are the six things this register cannot tell you. They are not caveats on the numbers; they are the boundary of what the numbers mean."
		>
			<ol class="limits">
				{#each LIMITATIONS as limitation (limitation.title)}
					<li>
						<h3>{limitation.title}</h3>
						<p>{limitation.body}</p>
					</li>
				{/each}
			</ol>
		</Plate>

		<Plate
			title="This build"
			note="Provenance for the dataset currently loaded. The commit and the generation time identify exactly which pipeline run produced every number on this site."
		>
			{#if manifest}
				<dl class="facts">
					<div>
						<dt>Generated</dt>
						<dd>{fmtTimestamp(manifest.generated_at)}</dd>
					</div>
					<div>
						<dt>Pipeline version</dt>
						<dd>{manifest.antilethe_version}</dd>
					</div>
					<div>
						<dt>Commit</dt>
						<dd class="mono">{manifest.git_sha.slice(0, 12)}</dd>
					</div>
					<div>
						<dt>Schema</dt>
						<dd>{manifest.schema_version}</dd>
					</div>
					<div>
						<dt>Archive span</dt>
						<dd>{index.span.days} days</dd>
					</div>
					<div>
						<dt>Complete days</dt>
						<dd>{index.span.complete_days}</dd>
					</div>
					<div>
						<dt>Questions with a series</dt>
						<dd>{index.span.series_questions} of {Object.keys(index.questions).length}</dd>
					</div>
					<div>
						<dt>Questions under this measure</dt>
						<dd>{index.span.measured_questions} of {index.span.series_questions}</dd>
					</div>
					<div class="full">
						<dt>Measures exported</dt>
						<dd class="mono">
							{manifest.methods_exported.length ? manifest.methods_exported.join(', ') : EM_DASH}
						</dd>
					</div>
					<div>
						<dt>Noise floor</dt>
						<dd class:nil={index.noise.median === null}>{fmt(index.noise.median)}</dd>
					</div>
					<div>
						<dt>Stable pairs</dt>
						<dd>{fmtInt(index.noise.n)}</dd>
					</div>
					<div>
						<dt>Adjacent-day pairs</dt>
						<dd>{fmtInt(index.gaps.adjacent)}</dd>
					</div>
					<div class="full">
						<dt>Multi-day pairs, excluded from the floor</dt>
						<dd>
							{fmtInt(index.gaps.multi_day)}{index.gaps.multi_day
								? ` across ${fmtInt(index.gaps.models_with_gaps)} models, longest gap ${index.gaps.max_days} days`
								: ''}
						</dd>
					</div>
					<div>
						<dt>index.json</dt>
						<dd>{fmtBytes(manifest.shard_bytes['index.json'] ?? null)}</dd>
					</div>
				</dl>
			{:else}
				<p class="hint">The build manifest is not available.</p>
			{/if}
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

	.strata {
		margin: 0;
		display: grid;
		gap: 1.1rem;
	}

	.strata dt {
		font-family: var(--font-mono);
		font-size: 0.82rem;
		display: flex;
		align-items: center;
		gap: 0.45em;
		margin-bottom: 0.3em;
	}

	.chip {
		width: 11px;
		height: 11px;
		border-radius: 2px;
		display: inline-block;
	}

	.chip.c1 {
		background: var(--c1);
	}
	.chip.c5 {
		background: var(--c5);
	}
	.chip.c2 {
		background: var(--c2);
	}

	.strata dd {
		margin: 0;
		font-size: 0.9rem;
		color: var(--ink-2);
		max-width: 74ch;
	}

	blockquote {
		margin: 0 0 1.2rem;
		padding-left: 0.9rem;
		border-left: 3px solid var(--accent);
		font-family: var(--font-display);
		font-size: 1.02rem;
		line-height: 1.5;
		color: var(--ink);
		max-width: 70ch;
	}

	.facts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 0.7rem 1.2rem;
		margin: 0;
	}

	.facts .full {
		grid-column: 1 / -1;
	}

	.facts dt {
		font-family: var(--font-mono);
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ink-3);
	}

	.facts dd {
		margin: 0.1em 0 0;
		font-family: var(--font-mono);
		font-size: 0.84rem;
		font-variant-numeric: tabular-nums;
	}

	.hash {
		font-size: 0.66rem;
		word-break: break-all;
		color: var(--ink-2);
	}

	.limits {
		margin: 0;
		padding-left: 1.3rem;
		display: grid;
		gap: 1.2rem;
	}

	.limits h3 {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--ink);
		margin-bottom: 0.35em;
	}

	.limits p {
		margin: 0;
		font-size: 0.9rem;
		color: var(--ink-2);
		max-width: 74ch;
	}

	.table-wrap {
		max-height: 420px;
		overflow: auto;
	}

	td.left {
		text-align: left;
	}

	.none {
		font-size: 0.94rem;
		margin-bottom: 0.6em;
	}

	.none-note {
		font-size: 0.84rem;
		color: var(--ink-3);
	}

	.hint {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: var(--ink-3);
		margin: 0;
	}
</style>
