<!--
	@component
	One model's stance on one question over the kept days.

	Three lines, one per hypothesis the stance probe scores each answer against
	(the answer says yes, says no, declines to take a position), each a
	probability from the entailment model. Only days the export kept are drawn,
	so the line has gaps by construction; a gap is a day not kept, not a day
	with no answer. The two days compared above are ringed.

	This is the measure that turns "the words changed" into "the position
	changed": a rewording leaves the three lines where they were, a reversal
	swaps the yes and no lines.
-->
<script lang="ts">
	import { LayerCake, Html, Svg } from 'layercake';
	import { scaleTime } from 'd3-scale';
	import AxisX from './layers/AxisX.svelte';
	import AxisY from './layers/AxisY.svelte';
	import HoverLayer from './layers/HoverLayer.svelte';
	import Line from './layers/Line.svelte';
	import Points from './layers/Points.svelte';
	import Legend from './Legend.svelte';
	import { EM_DASH, fmtPct, longDay, parseDay, shortDay } from '$lib/data/format';
	import type { Snapshot } from '$lib/data/types';

	interface Props {
		/** The model's kept snapshots on this question, keyed by day. */
		snapshots: Readonly<Record<string, Snapshot>>;
		dayA: string;
		dayB: string;
		height?: number;
	}

	let { snapshots, dayA, dayB, height = 220 }: Props = $props();

	interface Row {
		day: string;
		date: Date;
		yes: number | null;
		no: number | null;
		decline: number | null;
	}

	const SERIES = [
		{ key: 'yes', label: 'Says yes', color: 'var(--c1)' },
		{ key: 'no', label: 'Says no', color: 'var(--c5)' },
		{ key: 'decline', label: 'Declines to take a position', color: 'var(--c3)' }
	] as const;

	function prob(snap: Snapshot, key: string): number | null {
		const value = snap.features[key];
		return value === undefined || !Number.isFinite(value) ? null : value;
	}

	/** Only days whose snapshot carries the stance probe at all. */
	const rows = $derived.by<Row[]>(() =>
		Object.keys(snapshots)
			.sort()
			.map((day) => {
				const snap = snapshots[day] as Snapshot;
				return {
					day,
					date: parseDay(day),
					yes: prob(snap, 'stance_yes'),
					no: prob(snap, 'stance_no'),
					decline: prob(snap, 'stance_decline')
				};
			})
			.filter((row) => row.yes !== null)
	);

	/** Rings on the two compared days, at the "yes" value so they sit on a line. */
	const compared = $derived.by(() =>
		rows
			.filter((row) => row.day === dayA || row.day === dayB)
			.map((row) => ({
				x: row.date,
				y: row.yes,
				fill: 'transparent',
				title: `${longDay(row.day)}: compared above`
			}))
	);

	const legend = SERIES.map((s) => ({ label: s.label, color: s.color, shape: 'line' as const }));

	const description = $derived(
		`Stance probabilities over ${rows.length} kept days from ${rows.at(0)?.day ?? EM_DASH} to ` +
			`${rows.at(-1)?.day ?? EM_DASH}: whether each archived answer says yes, says no, or ` +
			`declines, as judged by the entailment model.`
	);
</script>

{#if rows.length === 0}
	<p class="empty">The stance probe did not run for this model on this question.</p>
{:else}
	<Legend entries={legend} />
	<div class="scroll">
		<div class="chart" style:height="{height}px">
			<LayerCake
				data={rows}
				x="date"
				y="yes"
				xScale={scaleTime()}
				yDomain={[0, 1]}
				padding={{ top: 12, right: 20, bottom: 40, left: 48 }}
			>
				<Svg label="Stance over time" describedBy="stance-timeline-desc">
					{#snippet title()}Stance over time{/snippet}
					<desc id="stance-timeline-desc">{description}</desc>
					<AxisY ticks={5} format={(v) => fmtPct(v, 0)} />
					<AxisX ticks={6} format={shortDay} />
					{#each SERIES as series (series.key)}
						<Line stroke={series.color} width={1.75} yKey={series.key} />
					{/each}
					<Points data={compared} r={6} stroke="var(--ink)" strokeWidth={1.5} />
				</Svg>
				<Html>
					<HoverLayer
						data={rows}
						snippet={tip}
						describe={(row) =>
							`${longDay(row.day)}: yes ${fmtPct(row.yes, 0)}, no ${fmtPct(row.no, 0)}, ` +
							`declines ${fmtPct(row.decline, 0)}`}
					/>
				</Html>
			</LayerCake>
		</div>
	</div>
{/if}

{#snippet tip(row: Row)}
	<div class="tip-day">{longDay(row.day)}</div>
	<div class="tip-row"><span class="k">says yes</span><span>{fmtPct(row.yes, 0)}</span></div>
	<div class="tip-row"><span class="k">says no</span><span>{fmtPct(row.no, 0)}</span></div>
	<div class="tip-row"><span class="k">declines</span><span>{fmtPct(row.decline, 0)}</span></div>
{/snippet}

<style>
	.scroll {
		overflow-x: auto;
	}

	.chart {
		position: relative;
		min-width: 320px;
	}

	.empty {
		color: var(--ink-3);
		font-size: 0.86rem;
	}

	.tip-day {
		color: var(--ink-3);
		margin-bottom: 0.25em;
	}

	.tip-row {
		display: flex;
		justify-content: space-between;
		gap: 1em;
	}

	.k {
		color: var(--ink-3);
	}
</style>
