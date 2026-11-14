<!--
	@component
	A question's answer space: every archived answer as a point in the plane of
	its first two principal embedding components, with one model's answers joined
	in day order so a reader can see it wander, settle, or jump.

	The plane is a property of the question. Its axes have no units and are not
	comparable across questions; what is comparable is distance within the plane,
	and the share of variance the plane keeps, which is stated in the note.

	Two days are highlighted: the pair the compare view currently shows. A pair
	that sits far apart in this plane is a pair whose meaning moved, under an
	embedding model's judgement, whatever the word diff looks like.
-->
<script lang="ts">
	import { LayerCake, Html, Svg } from 'layercake';
	import { scaleLinear } from 'd3-scale';
	import Paths from './layers/Paths.svelte';
	import Legend from './Legend.svelte';
	import Tooltip from './Tooltip.svelte';
	import { fmt, fmtPct, longDay, shortModel } from '$lib/data/format';
	import type { Snapshot } from '$lib/data/types';

	interface Props {
		/** model_id -> day -> snapshot, as the shard holds it. */
		models: Record<string, Record<string, Snapshot>>;
		/** The model whose path is drawn. */
		focus: string;
		/** The two days the compare view is showing. */
		dayA: string;
		dayB: string;
		height?: number;
	}

	let { models, focus, dayA, dayB, height = 380 }: Props = $props();

	interface Point {
		model_id: string;
		day: string;
		x: number;
		y: number;
		host: string | null;
	}

	/** Every answer with a map position, across all models. */
	const points = $derived.by<Point[]>(() => {
		const out: Point[] = [];
		for (const [model_id, byDay] of Object.entries(models)) {
			for (const [day, snap] of Object.entries(byDay)) {
				const x = snap.features.map_x;
				const y = snap.features.map_y;
				if (x === undefined || y === undefined) continue;
				out.push({ model_id, day, x, y, host: snap.serving_host });
			}
		}
		return out;
	});

	const focused = $derived(
		points.filter((p) => p.model_id === focus).sort((a, b) => a.day.localeCompare(b.day))
	);
	const others = $derived(points.filter((p) => p.model_id !== focus));

	/** Variance the two components keep, reported by the exporter per answer. */
	const variance = $derived.by(() => {
		for (const byDay of Object.values(models)) {
			for (const snap of Object.values(byDay)) {
				const v = snap.features.map_var;
				if (v !== undefined) return v;
			}
		}
		return null;
	});

	const marked = $derived(focused.filter((p) => p.day === dayA || p.day === dayB));

	/** Square plane: equal units on both axes, or distances would lie. */
	const extent = $derived.by(() => {
		if (points.length === 0)
			return { x: [0, 1] as [number, number], y: [0, 1] as [number, number] };
		const xs = points.map((p) => p.x);
		const ys = points.map((p) => p.y);
		const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
		const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
		const half = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 2;
		const pad = half * 1.08 || 1;
		return {
			x: [cx - pad, cx + pad] as [number, number],
			y: [cy - pad, cy + pad] as [number, number]
		};
	});

	let hovered = $state<Point | null>(null);
	let showTable = $state(false);

	const legend = $derived([
		{ label: `${shortModel(focus)}, day by day`, color: 'var(--c1)', shape: 'line' as const },
		{ label: 'Every other model', color: 'var(--ink-3)', shape: 'swatch' as const },
		{ label: 'The two days compared', color: 'var(--c2)', shape: 'swatch' as const }
	]);
</script>

{#if points.length === 0}
	<p class="hint">
		No answer-space positions in this build. They are produced by the <span class="mono"
			>embedding_map</span
		>
		method, which needs the <span class="mono">embedding</span> extra installed when the pipeline runs.
	</p>
{:else}
	<div class="head">
		<Legend entries={legend} />
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
				<caption class="sr-only">Answer-space position of {focus}, by day</caption>
				<thead>
					<tr>
						<th scope="col">Day</th>
						<th scope="col">Host</th>
						<th scope="col">x</th>
						<th scope="col">y</th>
					</tr>
				</thead>
				<tbody>
					{#each focused as p (p.day)}
						<tr>
							<th scope="row">{p.day}</th>
							<td class="left">{p.host ?? '—'}</td>
							<td>{fmt(p.x)}</td>
							<td>{fmt(p.y)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="chart" style:height="{height}px">
			<LayerCake
				data={focused}
				x="x"
				y="y"
				xScale={scaleLinear()}
				yScale={scaleLinear()}
				xDomain={extent.x}
				yDomain={extent.y}
				padding={{ top: 12, right: 12, bottom: 12, left: 12 }}
			>
				{#snippet children(k)}
					<Svg label="Answer space for one question" describedBy="traj-desc">
						{#snippet title()}Answer space{/snippet}
						<desc id="traj-desc"
							>Every archived answer to this question as a point in the plane of its first two
							principal embedding components. {shortModel(focus)}'s answers are joined in day order.
							{variance !== null
								? `The plane keeps ${fmtPct(variance)} of the variance.`
								: ''}</desc
						>
						<!-- The field: every other model's answers, faint. -->
						{#each others as p (p.model_id + p.day)}
							<circle
								cx={k.xGet(p)}
								cy={k.yGet(p)}
								r="2"
								fill="var(--ink-3)"
								opacity="0.35"
								role="img"
								aria-label="{p.model_id} on {p.day}"
								onpointerenter={() => (hovered = p)}
								onpointerleave={() => (hovered = null)}
							/>
						{/each}
						<Paths groups={[{ key: focus, rows: focused, stroke: 'var(--c1)', width: 1.5 }]} />
						{#each focused as p (p.day)}
							<circle
								cx={k.xGet(p)}
								cy={k.yGet(p)}
								r="3"
								fill="var(--c1)"
								stroke="var(--plate)"
								stroke-width="1"
								role="img"
								aria-label="{p.model_id} on {p.day}"
								onpointerenter={() => (hovered = p)}
								onpointerleave={() => (hovered = null)}
							/>
						{/each}
						{#each marked as p (p.day)}
							<circle
								cx={k.xGet(p)}
								cy={k.yGet(p)}
								r="7"
								fill="none"
								stroke="var(--c2)"
								stroke-width="2"
							/>
						{/each}
					</Svg>
					<Html pointerEvents={false}>
						{#if hovered}
							<Tooltip
								x={Number(k.xGet(hovered))}
								y={Number(k.yGet(hovered))}
								width={k.width}
								height={k.height}
							>
								<div class="tip-day">{longDay(hovered.day)}</div>
								<div>{hovered.model_id}</div>
								<div class="tip-k">{hovered.host ?? '—'}</div>
							</Tooltip>
						{/if}
					</Html>
				{/snippet}
			</LayerCake>
		</div>
	{/if}
{/if}

<style>
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1em;
		flex-wrap: wrap;
	}

	.chart {
		position: relative;
		min-width: 280px;
		max-width: 560px;
		margin: 0 auto;
	}

	.table-wrap {
		max-height: 380px;
		overflow: auto;
	}

	td.left {
		text-align: left;
	}

	.hint {
		font-family: var(--font-mono);
		font-size: 0.78rem;
		color: var(--ink-3);
		margin: 1rem 0;
		max-width: 60ch;
	}

	.tip-day {
		color: var(--ink-3);
	}

	.tip-k {
		color: var(--ink-3);
	}
</style>
