<script lang="ts">
	import { base } from '$app/paths';
	import DriftTimeline from '$lib/charts/DriftTimeline.svelte';
	import Decomposition from '$lib/charts/Decomposition.svelte';
	import DatasetGate from '$lib/components/DatasetGate.svelte';
	import Findings from '$lib/components/Findings.svelte';
	import HeroArt from '$lib/components/HeroArt.svelte';
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
		<section class="hero">
			<div class="copy">
				<h1 class="title">Anti&#8209;Lethe<span class="stop">.</span></h1>
				<p class="sub">A <span class="accent">drift register</span> for AI model behaviour.</p>
				<p class="lede">
					The Internet Archive asks the same {fmtInt(Object.keys(index.questions).length)} questions of
					{fmtInt(index.models.length)} models every day. This register reads that archive and reports
					how the answers moved between {longDay(index.span.first)} and {longDay(index.span.last)},
					with every answer hashed into a ledger so the record can be checked.
				</p>
				<p class="ctas">
					<a class="cta" href="https://github.com/tewodros18/the-anti-lethe-machine">
						<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"
							><path
								fill="currentColor"
								d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
							/></svg
						>
						tewodros18/the-anti-lethe-machine
					</a>
					<a
						class="cta"
						href="https://github.com/tewodros18/the-anti-lethe-machine/releases/tag/archive"
						>archive.db · {fmtInt(index.span.complete_days)} days</a
					>
					<a class="cta accent" href="{base}/method">how it is measured →</a>
				</p>
			</div>
			<div class="art"><HeroArt /></div>
		</section>

		<section class="intro">
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
				{#if index.span.series_questions < Object.keys(index.questions).length}
					The archive here holds a day-by-day series for {fmtInt(index.span.series_questions)} of the
					{fmtInt(Object.keys(index.questions).length)} questions in the catalogue.
				{/if}
			</p>
		</section>

		<ReadingStrip {readings} />

		<Findings {index} />

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
	.hero {
		display: grid;
		grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
		gap: 1rem 2rem;
		align-items: center;
		padding: 2.4rem 0 1.6rem;
	}

	.title {
		font-size: clamp(3.4rem, 2.2rem + 6vw, 6.4rem);
		font-weight: 400;
		line-height: 0.95;
		letter-spacing: -0.03em;
		margin-bottom: 0.3em;
	}

	.sub {
		font-family: var(--font-display);
		font-size: clamp(1.4rem, 1.1rem + 1.4vw, 2.1rem);
		line-height: 1.2;
		letter-spacing: -0.01em;
		color: var(--ink);
		margin-bottom: 0.7em;
	}

	.sub .accent {
		color: var(--accent);
	}

	.lede {
		font-family: var(--font-display);
		font-size: 1.12rem;
		line-height: 1.5;
		color: var(--ink-2);
		max-width: 52ch;
	}

	.ctas {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem;
		margin: 1.3rem 0 0;
		max-width: none;
	}

	.art {
		justify-self: end;
		max-width: 520px;
		width: 100%;
		color: var(--ink);
	}

	.intro {
		padding: 1.4rem 0 1.6rem;
		border-top: 1px dashed var(--rule-2);
	}

	.intro p {
		font-size: 0.98rem;
		color: var(--ink-2);
		max-width: 72ch;
	}

	.intro strong {
		color: var(--ink);
		font-weight: 500;
	}

	.method-link {
		font-size: 0.84rem;
		margin-bottom: 0;
	}

	@media (max-width: 820px) {
		.hero {
			grid-template-columns: 1fr;
			padding-top: 1.4rem;
		}

		.art {
			justify-self: center;
			max-width: 420px;
		}
	}
</style>
