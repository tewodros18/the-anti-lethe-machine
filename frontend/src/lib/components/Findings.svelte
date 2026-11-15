<!--
	@component
	The register's headline findings: the largest regime changes in a model's
	own noise, and the most unstable (question, model) pairs. Every row opens
	the compare page on the two archived answers that show it, so a reader can
	go from the claim to the evidence in one click. All numbers are under the
	active measure, named in the masthead.
-->
<script lang="ts">
	import { base } from '$app/paths';
	import Plate from '$lib/components/Plate.svelte';
	import { MIN_CELL_PAIRS, compareToken, regimeChanges, unstablePairs } from '$lib/data/findings';
	import { EM_DASH, fmt, fmtInt, fmtRatio, shortDay } from '$lib/data/format';
	import type { Index } from '$lib/data/types';

	interface Props {
		index: Index;
		limit?: number;
	}

	let { index, limit = 6 }: Props = $props();

	const regimes = $derived(regimeChanges(index, limit));
	const unstable = $derived(unstablePairs(index, limit));

	const CAUSE: Record<string, string> = {
		provider: 'coincides with a host switch',
		version: 'coincides with a rebuild'
	};
</script>

<Plate
	title="The largest shifts in the register"
	subtitle="Where a model's answers moved most, under the active measure, with the two archived answers that show it"
	note="A regime change is a break in a model's own day-to-day distance between consecutive answers, found by a changepoint detector over its stable transitions; the ratio divides the mean after the break by the mean before it. A recorded cause is a host switch or a rebuild within a day of the break; otherwise the drift has no cause the archive can name, which is a finding in itself, not an absence of one. The unstable pairs are the (question, model) cells with the highest mean adjacent-day distance over at least {MIN_CELL_PAIRS} pairs. Each link opens the compare page on two kept snapshot days, the nearest ones bracketing the event."
>
	<div class="grid">
		<section>
			<h3>Regime changes in a model's own noise</h3>
			{#if regimes.length === 0}
				<p class="empty">No changepoints under this measure.</p>
			{:else}
				<table>
					<thead>
						<tr>
							<th class="name">Model</th>
							<th>From</th>
							<th>Before</th>
							<th>After</th>
							<th>Ratio</th>
							<th class="cause">Recorded cause</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each regimes as finding (finding.changepoint.model_id + finding.changepoint.day)}
							<tr>
								<td class="name">
									{finding.name}
									<span class="vendor">{finding.vendor}</span>
								</td>
								<td class="mono">{shortDay(finding.changepoint.day)}</td>
								<td class="mono">{fmt(finding.changepoint.before_mean)}</td>
								<td class="mono">{fmt(finding.changepoint.after_mean)}</td>
								<td class="mono">{finding.ratio === null ? EM_DASH : fmtRatio(finding.ratio)}</td>
								<td class="cause">
									{finding.changepoint.coincides_with
										? CAUSE[finding.changepoint.coincides_with]
										: 'none recorded'}
								</td>
								<td class="link">
									{#if finding.selection}
										<a href="{base}/compare#{compareToken(finding.selection)}">side by side →</a>
									{:else}
										{EM_DASH}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>

		<section>
			<h3>The most unstable question–model pairs</h3>
			{#if unstable.length === 0}
				<p class="empty">No cell has {fmtInt(MIN_CELL_PAIRS)} adjacent-day pairs yet.</p>
			{:else}
				<table>
					<thead>
						<tr>
							<th class="name">Model</th>
							<th class="question">Question</th>
							<th>Mean distance</th>
							<th>Pairs</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each unstable as finding (finding.cell.question_slug + finding.cell.model_id)}
							<tr>
								<td class="name">
									{finding.name}
									<span class="vendor">{finding.vendor}</span>
								</td>
								<td class="question">{finding.questionText}</td>
								<td class="mono">{fmt(finding.cell.value)}</td>
								<td class="mono">{fmtInt(finding.cell.n)}</td>
								<td class="link">
									{#if finding.selection}
										<a href="{base}/compare#{compareToken(finding.selection)}">side by side →</a>
									{:else}
										{EM_DASH}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</section>
	</div>
</Plate>

<style>
	.grid {
		display: grid;
		gap: 1.4rem;
	}

	h3 {
		font-size: 0.86rem;
		font-weight: 500;
		margin: 0 0 0.5rem;
		color: var(--ink-2);
	}

	table {
		width: 100%;
	}

	.name {
		text-align: left;
		font-weight: 400;
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.vendor {
		display: block;
		color: var(--ink-3);
		font-size: 0.66rem;
	}

	.question,
	.cause {
		text-align: left;
		font-weight: 400;
	}

	td.question {
		max-width: 320px;
	}

	.link {
		text-align: right;
		white-space: nowrap;
	}

	.empty {
		color: var(--ink-3);
		font-size: 0.86rem;
	}
</style>
