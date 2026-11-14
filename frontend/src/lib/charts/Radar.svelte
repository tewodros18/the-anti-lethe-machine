<!--
	@component
	Six-axis comparison of 2–6 selected models.

	Every axis is min–max scaled across *the models currently shown*, so adding or
	removing a model changes every shape. That makes this a comparison and not a
	measurement, which the margin note states outright.

	Two choices keep the picture from lying:

	A floor. Plain min–max puts the lowest model on every axis at the exact
	centre, which reads as "nothing" when the real gap may be a few percent. The
	scale here runs from FLOOR to 1, and the innermost ring is drawn at the
	floor, so the lowest model still has a visible vertex and the centre is
	visibly off the scale.

	Flat axes. When the shown models do not differ on an axis (every one has
	zero refusals, say), min–max has no answer. Those axes are drawn at
	mid-radius for every model, their labels are muted, and the chart says which
	they are, instead of letting a ring at half radius read as "medium".

	Two axes are inverted so "further out" always means "more of the thing
	named": less drift is more stability, less latency is more speed.

	The `r` range is a function of the resolved plot size, so `RadarWeb` and every
	`RadarArea` read the same scale and cannot disagree about where 1.0 sits.
-->
<script lang="ts">
	import { LayerCake, Svg } from 'layercake';
	import { scaleLinear } from 'd3-scale';
	import RadarArea from './layers/RadarArea.svelte';
	import RadarWeb from './layers/RadarWeb.svelte';
	import Legend from './Legend.svelte';
	import { EM_DASH, fmt, fmtMs, fmtPct, fmtWords } from '$lib/data/format';
	import type { ModelFingerprint } from '$lib/data/types';

	interface Props {
		models: readonly ModelFingerprint[];
		height?: number;
	}

	let { models, height = 400 }: Props = $props();

	/** Scaled value of the lowest model on an axis; nothing plots below it. */
	export const FLOOR = 0.12;
	/** Where every model sits on an axis that does not vary among them. */
	const FLAT = 0.5;

	const SERIES = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)'];

	interface Axis {
		key: string;
		label: string;
		value: (model: ModelFingerprint) => number | null;
		format: (value: number) => string;
		/** True when a smaller raw number should sit further out. */
		invert?: boolean;
	}

	const AXES: Axis[] = [
		{
			key: 'stability',
			label: 'Stability',
			value: (m) => m.d_stable,
			format: (v) => fmt(v),
			invert: true
		},
		{ key: 'verbosity', label: 'Verbosity', value: (m) => m.mean_words, format: fmtWords },
		{ key: 'hedging', label: 'Hedging', value: (m) => m.hedge_rate, format: (v) => fmt(v, 2) },
		{ key: 'refusal', label: 'Refusal', value: (m) => m.refusal_rate, format: (v) => fmtPct(v) },
		{
			key: 'reasoning',
			label: 'Reasoning',
			value: (m) => m.reasoning_frac,
			format: (v) => fmtPct(v)
		},
		{
			key: 'speed',
			label: 'Speed',
			value: (m) => m.mean_duration_ms,
			format: (v) => fmtMs(v),
			invert: true
		}
	];

	const axisLabels = AXES.map((axis) => axis.label);

	/** Min and max of each axis across the shown models only. */
	const extents = $derived.by(() =>
		AXES.map((axis) => {
			const values = models
				.map((model) => axis.value(model))
				.filter((v): v is number => v !== null && Number.isFinite(v));
			return values.length
				? { min: Math.min(...values), max: Math.max(...values) }
				: { min: 0, max: 0 };
		})
	);

	/** Axes on which the shown models do not differ. */
	const flat = $derived(extents.map((e) => e.max === e.min));
	const flatLabels = $derived(AXES.filter((_, i) => flat[i]).map((a) => a.label));

	/** Scale one model's raw values onto [FLOOR, 1] against the shown-model extents. */
	function scaled(model: ModelFingerprint): (number | null)[] {
		return AXES.map((axis, i) => {
			const raw = axis.value(model);
			if (raw === null || !Number.isFinite(raw)) return null;
			if (flat[i]) return FLAT;
			const { min, max } = extents[i];
			const unit = (raw - min) / (max - min);
			const oriented = axis.invert ? 1 - unit : unit;
			return FLOOR + (1 - FLOOR) * oriented;
		});
	}

	const shapes = $derived.by(() =>
		models.map((model, i) => ({
			model,
			color: SERIES[i % SERIES.length],
			values: scaled(model)
		}))
	);

	const legend = $derived(
		shapes.map((s) => ({ label: s.model.name, color: s.color, shape: 'line' as const }))
	);

	let showTable = $state(false);
</script>

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
	<div class="scroll">
		<table>
			<caption class="sr-only">Model characteristics, raw values</caption>
			<thead>
				<tr>
					<th scope="col">Axis</th>
					{#each models as model (model.model_id)}
						<th scope="col">{model.name}</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each AXES as axis, i (axis.key)}
					<tr>
						<th scope="row"
							>{axis.label}{axis.invert ? ' (lower is further out)' : ''}{flat[i]
								? ' (no variation)'
								: ''}</th
						>
						{#each models as model (model.model_id)}
							{@const raw = axis.value(model)}
							<td class:nil={raw === null}>{raw === null ? EM_DASH : axis.format(raw)}</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<div class="chart" style:height="{height}px">
		<LayerCake
			rScale={scaleLinear()}
			rDomain={[0, 1]}
			rRange={({ width, height: h }) => [0, Math.max(10, Math.min(width, h) / 2)]}
			padding={{ top: 30, right: 84, bottom: 30, left: 84 }}
		>
			<Svg label="Model comparison across six axes" describedBy="radar-desc">
				{#snippet title()}Model comparison across six axes{/snippet}
				<desc id="radar-desc"
					>A radar chart comparing {models.length} models across stability, verbosity, hedging, refusal,
					reasoning and speed. Each axis is scaled between the lowest and highest value among the models
					shown, so positions are relative to this selection only. The lowest model on an axis sits on
					the innermost ring, not at the centre.{flatLabels.length
						? ` The models shown do not differ on ${flatLabels.join(', ')}; those axes are drawn at mid-radius.`
						: ''}</desc
				>
				<RadarWeb axes={axisLabels} levels={4} floor={FLOOR} muted={flat} />
				{#each shapes as shape (shape.model.model_id)}
					<RadarArea values={shape.values} color={shape.color} label={shape.model.name} />
				{/each}
			</Svg>
		</LayerCake>
	</div>
	{#if flatLabels.length}
		<p class="flat-note">
			No variation among the models shown on {flatLabels.join(', ')} — drawn at mid-radius, not as a measurement.
		</p>
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
	}

	.scroll {
		overflow-x: auto;
	}

	.flat-note {
		margin: 0.4em 0 0;
		font-family: var(--font-mono);
		font-size: 0.7rem;
		color: var(--ink-3);
		max-width: 60ch;
	}
</style>
