/**
 * The data contract, mirroring `backend/src/antilethe/models.py` field-for-field.
 *
 * `number | null` is load-bearing everywhere it appears. A null means either
 * that upstream never supplied the value or that there was not enough data to
 * compute it honestly. It is never a zero, and the UI renders it as an em dash.
 */

export type Stratum = 'stable' | 'provider' | 'version';

export interface MethodRef {
	name: string;
	version: string;
}

export interface Span {
	first: string;
	last: string;
	days: number;
	complete_days: number;
	/** Questions with answers on more than one day, i.e. with a series. */
	series_questions: number;
	/** Questions with at least one distance under this measure. */
	measured_questions: number;
}

export interface NoiseStats {
	n: number;
	mean: number | null;
	median: number | null;
	p05: number | null;
	p25: number | null;
	p75: number | null;
	p95: number | null;
	p99: number | null;
	std: number | null;
	insufficient_data: boolean;
}

export interface TimelinePoint {
	day: string;
	stable: number | null;
	provider: number | null;
	version: number | null;
	n_stable: number;
	n_provider: number;
	n_version: number;
}

export interface StratumStat {
	mean: number | null;
	n: number;
}

/** A ratio taken inside each model, then summarised across models. */
export interface WithinStat {
	median: number;
	q25: number;
	q75: number;
	/** Models with pairs in both strata, i.e. with a ratio of their own. */
	n: number;
	/** How many of them have a ratio above one. */
	above_one: number;
}

export interface Decomposition {
	stable: StratumStat;
	provider: StratumStat;
	version: StratumStat;
	/** provider.mean / stable.mean, pooled over every pair */
	provider_ratio: number | null;
	/** version.mean / stable.mean, pooled over every pair */
	version_ratio: number | null;
	/** 95% percentile-bootstrap interval for the pooled ratio; null whenever it is. */
	provider_ratio_ci: [number, number] | null;
	version_ratio_ci: [number, number] | null;
	/** The same ratio inside each model, summarised; null under three models. */
	provider_within: WithinStat | null;
	version_within: WithinStat | null;
}

export interface Changepoint {
	model_id: string;
	/** First day of the new regime. */
	day: string;
	before_mean: number;
	after_mean: number;
	delta: number;
	n_before: number;
	n_after: number;
	/** A known event within a day of the break, or null for unexplained drift. */
	coincides_with: 'version' | 'provider' | null;
}

export interface ModelFingerprint {
	model_id: string;
	name: string;
	vendor: string;
	n_answers: number;
	mean_words: number;
	refusal_rate: number;
	hedge_rate: number;
	reasoning_frac: number;
	mean_duration_ms: number;
	mean_cost: number;
	d_stable: number | null;
	d_provider: number | null;
	d_version: number | null;
	noise: NoiseStats;
	repoints: number;
	host_switches: number;
	hosts_seen: string[];
	/**
	 * Per-day mean over this model's STABLE transitions, index-aligned to
	 * `Index.timeline`. Feeds the sparkline in the model table. A day on which
	 * the model contributed no stable pair is null, so the line breaks rather
	 * than implying a measurement of zero.
	 */
	daily: (number | null)[];
}

export interface InstabilityCell {
	question_slug: string;
	model_id: string;
	value: number;
	n: number;
}

export interface VersionEvent {
	day: string;
	model_id: string;
	from_canonical: string | null;
	to_canonical: string | null;
}

export interface ProviderEvent {
	day: string;
	model_id: string;
	from_host: string | null;
	to_host: string | null;
}

export interface PriceChange {
	day: string;
	model_id: string;
	prompt_price: number | null;
	completion_price: number | null;
}

export interface QuestionMeta {
	text: string;
	tags: string[];
}

/**
 * Transitions that compare adjacent days versus those spanning a gap. The noise
 * floor and strata comparison use adjacent-day transitions only.
 */
export interface GapSummary {
	adjacent: number;
	multi_day: number;
	/** Longest gap seen, in days; 1 when there are none. */
	max_days: number;
	models_with_gaps: number;
}

export interface Index {
	schema_version: 1;
	generated_at: string;
	method: MethodRef;
	span: Span;
	noise: NoiseStats;
	gaps: GapSummary;
	timeline: TimelinePoint[];
	decomposition: Decomposition;
	models: ModelFingerprint[];
	questions: Record<string, QuestionMeta>;
	cells: InstabilityCell[];
	version_events: VersionEvent[];
	provider_events: ProviderEvent[];
	price_changes: PriceChange[];
	/** question_slug -> days available in that question's shard */
	snapshot_days: Record<string, string[]>;
	changepoints: Changepoint[];
}

export interface Snapshot {
	/** First 4000 characters of the archived answer. */
	text: string;
	truncated: boolean;
	/** SHA-256 of the FULL answer, 64 hex characters. */
	sha256: string;
	canonical_slug: string | null;
	serving_host: string | null;
	duration_ms: number | null;
	word_count: number;
	refusal: boolean;
	/**
	 * Every per-answer feature an installed feature method produced: marker
	 * probes, token counts, the stance distribution, and `map_x` / `map_y` in
	 * the question's embedding plane. Absent features are absent, not zero.
	 */
	features: Record<string, number>;
}

export interface SnapshotShard {
	question_slug: string;
	question_text: string;
	/** model_id -> day -> snapshot */
	models: Record<string, Record<string, Snapshot>>;
}

export interface InstalledMethod {
	name: string;
	kind: string;
	version: string;
	/** For a model-backed method, the checkpoint that produced its numbers. */
	model: string | null;
}

export interface LedgerHead {
	day: string;
	merkle_root: string;
}

export interface Manifest {
	schema_version: 1;
	generated_at: string;
	git_sha: string;
	antilethe_version: string;
	methods_installed: InstalledMethod[];
	/** Methods with a full index in this build; the first is index.json. */
	methods_exported: string[];
	ledger_head: LedgerHead | null;
	row_count: number;
	shard_bytes: Record<string, number>;
}

export type DiffOp = 'equal' | 'insert' | 'delete';

export interface DiffToken {
	op: DiffOp;
	text: string;
}
