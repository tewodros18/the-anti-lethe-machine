<!--
	@component
	Question × model instability, as a single-hue opacity grid.

	Every cell is the mean distance over STABLE transitions only. Holding the
	build and the host fixed is what makes the grid about the questions: a dark
	row is a question that models answer differently from day to day even when
	nothing underneath them changed.
-->
<script lang="ts">
	import { LayerCake, Svg } from 'layercake';
	import { scaleBand, scaleLinear } from 'd3-scale';
	import AxisX from './layers/AxisX.svelte';
	import Cells from './layers/Cells.svelte';
	import { fmt, fmtInt, shortModel } from '$lib/data/format';
	import type { InstabilityCell, QuestionMeta } from '$lib/data/types';

	interface Props {
		cells: readonly InstabilityCell[];
		questions: Record<string, QuestionMeta>;
		/** Rows to show, highest mean first. */
		maxQuestions?: number;
	}

	let { cells, questions, maxQuestions = 28 }: Props = $props();

	/** Questions ordered by their mean instability, truncated to the top rows. */
	const questionOrder = $derived.by(() => {
		const totals = new Map<string, { sum: number; n: number }>();
		for (const cell of cells) {
			const entry = totals.get(cell.question_slug) ?? { sum: 0, n: 0 };
			entry.sum += cell.value;
			entry.n += 1;
			totals.set(cell.question_slug, entry);
		}
		return [...totals.entries()]
			.sort((a, b) => b[1].sum / b[1].n - a[1].sum / a[1].n)
			.slice(0, maxQuestions)
			.map(([slug]) => slug);
	});

	const modelOrder = $derived.by(() =>
		[...new Set(cells.map((cell) => cell.model_id))].sort((a, b) => a.localeCompare(b))
	);

	const shown = $derived.by(() => {
		const keep = new Set(questionOrder);
		return cells.filter((cell) => keep.has(cell.question_slug));
	});

	const maxValue = $derived(Math.max(0.0001, ...shown.map((cell) => cell.value)));

	/** Opacity floor keeps a measured-but-tiny cell visible rather than blank. */
	const opacityScale = $derived(scaleLinear().domain([0, maxValue]).range([0.06, 1]));

	/** Height follows the row count so cells stay square-ish and readable. */
	const height = $derived(Math.max(200, questionOrder.length * 17 + 46));
	/** Width needed before the grid gets cramped; the wrapper scrolls past it. */
	const minWidth = $derived(Math.max(420, modelOrder.length * 20 + 240));

	let showTable = $state(false);
	let hovered = $state<InstabilityCell | null>(null);

	function questionText(slug: string): string {
		return questions[slug]?.text ?? slug;
	}
</script>

<div class="head">
	<p class="hint" aria-live="polite">
		{#if hovered}
			<strong>{fmt(hovered.value)}</strong>
			&middot; {shortModel(hovered.model_id)} &middot; {questionText(hovered.question_slug)}
			<span class="n">({fmtInt(hovered.n)} pairs)</span>
		{:else}
			Darker means an answer that moves more from day to day with the build and host unchanged.
		{/if}
	</p>
	<button
		class="btn"
		aria-pressed={showTable}
		onclick={() => (showTable = !showTable)}
		type="button">Show as table</button
	>
</div>

{#if showTable}
	<div class="table-wrap">
		<table>
			<caption class="sr-only">Mean stable-stratum distance per question and model</caption>
			<thead>
				<tr>
					<th scope="col">Question</th>
					<th scope="col">Model</th>
					<th scope="col">Mean distance</th>
					<th scope="col">Pairs</th>
				</tr>
			</thead>
			<tbody>
				{#each shown as cell (cell.question_slug + cell.model_id)}
					<tr>
						<th scope="row">{questionText(cell.question_slug)}</th>
						<td class="left">{cell.model_id}</td>
						<td>{fmt(cell.value)}</td>
						<td>{fmtInt(cell.n)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<div class="scroll">
		<div class="chart" style:height="{height}px" style:min-width="{minWidth}px">
			<LayerCake
				data={shown}
				x="model_id"
				y="question_slug"
				xScale={scaleBand()}
				yScale={scaleBand()}
				xDomain={modelOrder}
				yDomain={questionOrder}
				padding={{ top: 4, right: 4, bottom: 42, left: 236 }}
			>
				<Svg label="Question by model instability" describedBy="heatmap-desc">
					{#snippet title()}Question by model instability{/snippet}
					<desc id="heatmap-desc"
						>A grid of {questionOrder.length} questions by {modelOrder.length} models. Each cell's opacity
						is the mean distance between consecutive archived answers for pairs where the model build
						and serving host both stayed the same.</desc
					>
					<Cells
						opacity={(row) => Number(opacityScale(Number(row.value)))}
						title={(row) =>
							`${questionText(String(row.question_slug))} — ${row.model_id}: ${fmt(Number(row.value))} over ${row.n} pairs`}
						onhover={(row) => (hovered = (row as unknown as InstabilityCell) ?? null)}
					/>
					<AxisX ticks={modelOrder.length} format={shortModel} rotate={-45} />
				</Svg>
			</LayerCake>
			<!-- Row labels are real text outside the SVG so they wrap and can be
			     selected; the band scale's order is mirrored here. -->
			<ul class="rows" style:top="4px">
				{#each questionOrder as slug (slug)}
					<li style:height="{(height - 46) / questionOrder.length}px" title={questionText(slug)}>
						{questionText(slug)}
					</li>
				{/each}
			</ul>
		</div>
	</div>
{/if}

<style>
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1em;
		flex-wrap: wrap;
	}

	.hint {
		margin: 0 0 0.5em;
		font-family: var(--font-mono);
		font-size: 0.72rem;
		color: var(--ink-2);
		max-width: 56ch;
	}

	.hint .n {
		color: var(--ink-3);
	}

	.scroll {
		overflow-x: auto;
	}

	.chart {
		position: relative;
	}

	.rows {
		position: absolute;
		left: 0;
		width: 228px;
		margin: 0;
		padding: 0;
		list-style: none;
		pointer-events: none;
	}

	.rows li {
		display: flex;
		align-items: center;
		font-size: 0.68rem;
		line-height: 1.1;
		color: var(--ink-2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		padding-right: 8px;
	}

	.table-wrap {
		max-height: 460px;
		overflow: auto;
	}

	td.left {
		text-align: left;
		font-size: 0.75rem;
	}
</style>
