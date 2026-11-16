<!--
	@component
	Two archived answers side by side, with a verdict above them.

	The verdict is the point of this view. The same visible difference means
	different things depending on which stratum the pair falls in, so the
	stratum is stated in words before a reader looks at the text.

	Each pane carries its own canonical build, serving host and full SHA-256, so
	the claim being made about the pair is checkable against the ledger.
-->
<script lang="ts">
	import DiffText from './DiffText.svelte';
	import { changeFraction, wordDiff } from '$lib/data/diff';
	import { EM_DASH, fmt, fmtInt, fmtMs, fmtPct, longDay } from '$lib/data/format';
	import type { LedgerDay, Snapshot, Stratum } from '$lib/data/types';

	interface Props {
		questionText: string;
		modelId: string;
		dayA: string;
		dayB: string;
		a: Snapshot | null;
		b: Snapshot | null;
		/** The hash chain by day, when the build's manifest carries it. */
		ledger?: Record<string, LedgerDay>;
	}

	let { questionText, modelId, dayA, dayB, a, b, ledger = {} }: Props = $props();

	const tokens = $derived(wordDiff(a?.text ?? '', b?.text ?? ''));
	const changed = $derived(changeFraction(tokens));

	const identical = $derived(a !== null && b !== null && a.sha256 === b.sha256);

	/**
	 * Which stratum this pair falls in, by exact string comparison of the build
	 * and host. Computed here rather than read from the dataset because the two
	 * days a reader picks need not be adjacent in the series.
	 */
	const stratum = $derived.by<Stratum | null>(() => {
		if (!a || !b) return null;
		if (
			a.canonical_slug !== null &&
			b.canonical_slug !== null &&
			a.canonical_slug !== b.canonical_slug
		)
			return 'version';
		if (a.serving_host !== null && b.serving_host !== null && a.serving_host !== b.serving_host)
			return 'provider';
		return 'stable';
	});

	const VERDICTS: Record<Stratum, { title: string; body: string; tone: string }> = {
		stable: {
			title: 'Same build, same host',
			body:
				'The model build and the serving host are identical on both days. Any difference below is ' +
				'sampling noise: the same system answering the same question twice. This is the baseline ' +
				'every other comparison is measured against, not a finding.',
			tone: 'good'
		},
		provider: {
			title: 'Same build, different host',
			body:
				'The model build is identical, but the two answers were generated on different inference ' +
				'hosts. Quantisation and serving stack differ; the weights do not. A difference here is ' +
				'infrastructure, not a change in the model.',
			tone: 'warn'
		},
		version: {
			title: 'Different build',
			body:
				'The model-id alias pointed at a different dated build on these two days. This is detected ' +
				'by exact string comparison and carries no statistical uncertainty: the model itself ' +
				'changed. This is the only category where a difference is unambiguously the model.',
			tone: 'critical'
		}
	};

	const verdict = $derived(stratum ? VERDICTS[stratum] : null);
</script>

<div class="verdict-wrap">
	{#if verdict}
		<div class="verdict {verdict.tone}">
			<h3>{verdict.title}</h3>
			<p>{verdict.body}</p>
			<p class="measured">
				{#if identical}
					The two archived answers are byte-identical: the hashes match.
				{:else}
					{fmtPct(changed)} of words differ between the two answers.
				{/if}
			</p>
		</div>
	{:else}
		<div class="verdict">
			<h3>No pair to compare</h3>
			<p>
				The archive does not hold a snapshot for this model on both of the selected days. Pick two
				days that both appear in the day list.
			</p>
		</div>
	{/if}
</div>

{#if ledger[dayA] || ledger[dayB]}
	<p class="verify">
		Each day's root is the Merkle root over the sorted SHA-256 of every answer archived that day,
		chained to the previous day's root. The hash shown in each pane is one of those leaves. To check
		a day yourself, restore the archive from the release and run
		<code>antilethe verify --day {dayA}</code>: it recomputes the root from the stored rows and
		exits non-zero if anything was altered. The ledger proves a record has not changed since it was
		fetched; it cannot prove which model produced it.
	</p>
{/if}

<div class="panes">
	<!-- Keyed by side, never by day: the two days are equal while the pair is
	     still being chosen, and a duplicate key would throw. -->
	{#each [{ snap: a, day: dayA, side: 'before' as const }, { snap: b, day: dayB, side: 'after' as const }] as pane (pane.side)}
		<article class="pane">
			<header>
				<h4>{longDay(pane.day)}</h4>
				<dl>
					<div>
						<dt>Build</dt>
						<dd class:nil={!pane.snap?.canonical_slug}>{pane.snap?.canonical_slug ?? EM_DASH}</dd>
					</div>
					<div>
						<dt>Host</dt>
						<dd class:nil={!pane.snap?.serving_host}>{pane.snap?.serving_host ?? EM_DASH}</dd>
					</div>
					<div>
						<dt>Latency</dt>
						<dd>{fmtMs(pane.snap?.duration_ms ?? null)}</dd>
					</div>
					<div>
						<dt>Words</dt>
						<dd>{pane.snap ? pane.snap.word_count : EM_DASH}</dd>
					</div>
					{#if pane.snap?.features.token_count !== undefined}
						<div>
							<dt>Tokens</dt>
							<dd>{Math.round(pane.snap.features.token_count)}</dd>
						</div>
					{/if}
					{#if pane.snap?.features.stance_yes !== undefined}
						<!-- The zero-shot stance probe: what the answer asserts, by entailment. -->
						<div class="full stance">
							<dt>Stance probe (yes / no / declines)</dt>
							<dd>
								<span class="bar" aria-hidden="true">
									<span
										class="seg yes"
										style:width="{(pane.snap.features.stance_yes * 100).toFixed(1)}%"
									></span>
									<span
										class="seg no"
										style:width="{((pane.snap.features.stance_no ?? 0) * 100).toFixed(1)}%"
									></span>
									<span
										class="seg decline"
										style:width="{((pane.snap.features.stance_decline ?? 0) * 100).toFixed(1)}%"
									></span>
								</span>
								{fmtPct(pane.snap.features.stance_yes, 0)} / {fmtPct(
									pane.snap.features.stance_no ?? 0,
									0
								)} / {fmtPct(pane.snap.features.stance_decline ?? 0, 0)}
							</dd>
						</div>
					{/if}
					<div class="full">
						<dt>SHA-256 of full answer</dt>
						<dd class="hash">{pane.snap?.sha256 ?? EM_DASH}</dd>
					</div>
					{#if ledger[pane.day]}
						<div class="full">
							<dt>Day's Merkle root, {fmtInt(ledger[pane.day]?.row_count ?? null)} leaves</dt>
							<dd class="hash">{ledger[pane.day]?.merkle_root}</dd>
						</div>
					{/if}
				</dl>
			</header>
			{#if pane.snap}
				<DiffText {tokens} side={pane.side} />
				{#if pane.snap.truncated}
					<p class="trunc">Shown to 4000 characters. The hash above is of the complete answer.</p>
				{/if}
			{:else}
				<p class="absent">No archived answer for this model on this day.</p>
			{/if}
		</article>
	{/each}
</div>

<p class="context">
	<span class="ck">Question</span>
	{questionText}
	<span class="ck">Model</span> <span class="mono">{modelId}</span>
	{#if a && b}
		<span class="ck">Distance</span>
		<span class="mono">{fmt(changed)}</span>
		<span class="cn">(share of words changed, not the dataset's method score)</span>
	{/if}
</p>

<style>
	.verdict-wrap {
		margin-bottom: 1rem;
	}

	.verdict {
		border-left: 3px solid var(--rule-2);
		padding: 0.1rem 0 0.1rem 0.85rem;
	}

	.verdict.good {
		border-left-color: var(--good);
	}
	.verdict.warn {
		border-left-color: var(--warn);
	}
	.verdict.critical {
		border-left-color: var(--critical);
	}

	.verdict h3 {
		font-family: var(--font-mono);
		font-size: 0.74rem;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--ink-3);
		margin-bottom: 0.3em;
	}

	.verdict p {
		margin: 0 0 0.4em;
		font-size: 0.9rem;
	}

	.measured {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: var(--ink-2);
	}

	.panes {
		display: grid;
		grid-template-columns: 1fr;
		gap: 1rem;
	}

	@media (min-width: 900px) {
		.panes {
			grid-template-columns: 1fr 1fr;
		}
	}

	.pane {
		border: 1px solid var(--rule);
		border-radius: var(--radius);
		background: var(--paper);
		padding: 0.8rem;
		min-width: 0;
	}

	.pane header {
		border-bottom: 1px solid var(--rule);
		padding-bottom: 0.6rem;
		margin-bottom: 0.7rem;
	}

	.pane h4 {
		font-family: var(--font-mono);
		font-size: 0.8rem;
		margin-bottom: 0.45em;
	}

	dl {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
		gap: 0.3em 0.8em;
		margin: 0;
	}

	dl .full {
		grid-column: 1 / -1;
	}

	dt {
		font-family: var(--font-mono);
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ink-3);
	}

	dd {
		margin: 0;
		font-family: var(--font-mono);
		font-size: 0.72rem;
		overflow-wrap: break-word;
	}

	.hash {
		font-size: 0.64rem;
		color: var(--ink-2);
		word-break: break-all;
	}

	.stance dd {
		display: flex;
		align-items: center;
		gap: 0.6em;
	}

	.bar {
		display: inline-flex;
		width: 120px;
		height: 8px;
		border-radius: 2px;
		overflow: hidden;
		background: var(--sunk);
		flex: none;
	}

	.seg {
		display: block;
		height: 100%;
	}

	.seg.yes {
		background: var(--good);
	}
	.seg.no {
		background: var(--critical);
	}
	.seg.decline {
		background: var(--warn);
	}

	.trunc,
	.absent {
		margin: 0.7em 0 0;
		font-size: 0.72rem;
		color: var(--ink-3);
		font-family: var(--font-mono);
	}

	.context {
		margin: 1rem 0 0;
		padding-top: 0.8rem;
		border-top: 1px solid var(--rule);
		font-size: 0.8rem;
		color: var(--ink-2);
		max-width: none;
	}

	.ck {
		font-family: var(--font-mono);
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ink-3);
		margin-right: 0.35em;
		margin-left: 0.9em;
	}

	.context .ck:first-child {
		margin-left: 0;
	}

	.cn {
		color: var(--ink-3);
		font-size: 0.72rem;
	}

	.verify {
		font-size: 0.8rem;
		color: var(--ink-2);
		margin: 0 0 0.9rem;
	}

	.verify code {
		font-family: var(--font-mono);
		font-size: 0.78rem;
	}
</style>
