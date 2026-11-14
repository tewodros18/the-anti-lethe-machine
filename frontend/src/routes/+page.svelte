<script lang="ts">
	import { base } from '$app/paths';
	import DriftTimeline from '$lib/charts/DriftTimeline.svelte';
	import Decomposition from '$lib/charts/Decomposition.svelte';
	import DatasetGate from '$lib/components/DatasetGate.svelte';
	import Plate from '$lib/components/Plate.svelte';
	import ReadingStrip from '$lib/components/ReadingStrip.svelte';
	import { EM_DASH, fmt, fmtInt, fmtRatio, longDay } from '$lib/data/format';
	import { dataset } from '$lib/state/dataset.svelte';

	const index = $derived(dataset.index);

	/** What the active measure can and cannot see, for the plate notes. */
	const MEASURE_NOTES: Record<string, string> = {
		cosine_bow:
			'The distance measure counts word frequencies, so it registers rewording and would miss a reversal that reuses the same vocabulary.',
		jaccard_ngram:
			'The distance measure is trigram-shingle overlap, so it registers reordering and rephrasing; a reversal that keeps most phrases scores as a small edit.',
		ncd: 'The distance measure is compression distance, so it registers shared structure and order; it is blind to negation like every surface measure.',
		embedding:
			'The distance measure is sentence-embedding cosine, so it registers change in meaning and ignores rewording; negation moves it far less than it moves the meaning.',
		nli: 'The distance is P(contradiction) from a natural-language-inference model, so a reversal scores near 1 and a rewording near 0; it says nothing about how much the wording moved.'
	};
	const measureNote = $derived(
		(index && MEASURE_NOTES[index.method.name]) ??
			'The distance measure is named in the masthead; see the method page for what it can and cannot see.'
	);

	const readings = $derived.by(() => {
		if (!index) return [];
		return [
			{
				label: 'Host effect',
				value:
					index.decomposition.provider_within !== null
						? fmtRatio(index.decomposition.provider_within.median)
						: index.decomposition.provider_ratio === null
							? EM_DASH
							: fmtRatio(index.decomposition.provider_ratio),
				note:
					index.decomposition.provider_within !== null
						? `within model, median of ${fmtInt(index.decomposition.provider_within.n)}`
						: 'host switch ÷ noise, pooled',
				lead: true
			},
			{
				label: 'Rebuild effect',
				value:
					index.decomposition.version_ratio === null
						? EM_DASH
						: fmtRatio(index.decomposition.version_ratio),
				note: index.decomposition.version.n === 0 ? 'none observed' : 'rebuild ÷ noise',
				lead: true
			},
			{
				label: 'Days',
				value: fmtInt(index.span.days),
				note: `${fmtInt(index.span.complete_days)} complete`
			},
			{
				label: 'Questions',
				value: fmtInt(index.span.series_questions),
				note: `of ${fmtInt(Object.keys(index.questions).length)} with a series`
			},
			{ label: 'Models', value: fmtInt(index.models.length) },
			{
				label: 'Noise median',
				value: fmt(index.noise.median),
				note: index.noise.insufficient_data ? 'too few pairs' : `n=${fmtInt(index.noise.n)}`
			},
			{ label: 'Host switches', value: fmtInt(index.provider_events.length) },
			{ label: 'Rebuilds', value: fmtInt(index.version_events.length) }
		];
	});
</script>

<svelte:head>
	<title>Anti-Lethe — a drift register for model behaviour</title>
</svelte:head>

<DatasetGate>
	{#if index}
		<section class="lede">
			<h1>What changed, and why it changed</h1>
			<p>
				The Internet Archive asks the same {fmtInt(Object.keys(index.questions).length)} questions of
				the same {fmtInt(index.models.length)} models every day. This register reads that archive and
				reports how the answers moved between
				{longDay(index.span.first)} and {longDay(index.span.last)}.
				{#if index.span.series_questions < Object.keys(index.questions).length}
					It currently holds a day-by-day series for {fmtInt(index.span.series_questions)} of those questions;
					the rest are in the catalogue but not yet in the archive here.
				{/if}
			</p>
			<p>
				A changed answer has three possible causes, and reporting them as one number would be
				meaningless. <strong>Sampling noise</strong> is the same build on the same host answering
				twice. <strong>A host switch</strong> is the same weights served by a different inference
				provider, with a different quantisation and serving stack. <strong>A rebuild</strong> is the vendor
				repointing a model-id alias at new weights — the only case where the model itself changed, detected
				by exact string comparison rather than by measuring text.
			</p>
			<p class="method-link">
				Every number here is computed by <span class="mono">{index.method.name}</span>
				v{index.method.version}.
				{#if dataset.methods.length > 1}
					Switch the measure in the masthead to see the same register under another.
				{/if}
				<a href="{base}/method">What it can and cannot see →</a>
			</p>
		</section>

		<div class="strip-wrap">
			<ReadingStrip {readings} />
		</div>

		<Plate
			title="Drift against its own noise floor"
			subtitle="Mean distance between consecutive archived answers, same build and same host"
			note="The line is only pairs where the model build and the serving host were both unchanged, so it is sampling noise and nothing else. The shaded band is the 5th to 95th percentile of that same distribution, and the dashed rule its median: anything inside the band is indistinguishable from the model answering twice. Vertical rules mark days when a serving host changed (dashed) or a model build changed (solid). This chart does not show what changed in any answer, only how far it moved under the {index
				.method.name} measure. {measureNote}"
		>
			<DriftTimeline
				timeline={index.timeline}
				noise={index.noise}
				versionEvents={index.version_events}
				providerEvents={index.provider_events}
			/>
		</Plate>

		<Plate
			title="Where the movement comes from"
			subtitle="Mean distance within each cause of change"
			note="Each bar is a mean over a different population of day-to-day pairs, and the two ratios divide the other bars by the first. A stratum with no observed pairs has no bar and no ratio: it is shown as an em dash rather than a zero, because no measurement is not the same as no change. The ratio compares populations: host switches happen almost only to open-weight models, so the per-model host effect in the model table is the fairer comparison. {measureNote}"
		>
			<Decomposition decomposition={index.decomposition} />
		</Plate>
	{/if}
</DatasetGate>

<style>
	.lede {
		margin-bottom: 1.4rem;
	}

	.lede h1 {
		margin-bottom: 0.6rem;
	}

	.lede p {
		font-size: 0.98rem;
		color: var(--ink-2);
	}

	.lede strong {
		color: var(--ink);
		font-weight: 500;
	}

	.method-link {
		font-size: 0.84rem;
	}

	.strip-wrap {
		border-top: 1px solid var(--rule-2);
		border-bottom: 1px solid var(--rule-2);
		padding: 0.5rem 0;
		margin-bottom: 1.5rem;
	}
</style>
