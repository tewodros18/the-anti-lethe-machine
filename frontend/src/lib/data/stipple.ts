/**
 * A deterministic stipple: dots laid under a profile, denser at the base.
 *
 * Used for the hero illustration, a mound of dots with a survey mark on top.
 * The generator is seeded so the drawing is the same on every render and on
 * every machine; nothing about it is random at run time, which also keeps
 * server and client markup identical.
 */

export interface Dot {
	x: number;
	y: number;
	r: number;
}

/** Park–Miller minimal standard generator; enough for dots on a page. */
function lcg(seed: number): () => number {
	let state = seed % 2147483647;
	if (state <= 0) state += 2147483646;
	return () => {
		state = (state * 16807) % 2147483647;
		return (state - 1) / 2147483646;
	};
}

/**
 * Height of the mound at horizontal position `t` in [0, 1], as a fraction of
 * the full height: a skewed bell, taller towards `peak`.
 */
export function moundProfile(t: number, peak = 0.62): number {
	const d = t - peak;
	const width = d < 0 ? 0.42 : 0.3;
	return Math.exp(-(d * d) / (2 * width * width));
}

/**
 * Dots for a mound `width` by `height`, with the mound's base at `y = height`.
 * Density falls off towards the crest, so the silhouette is soft rather than
 * hard-edged; dot radius shrinks with height for the same reason.
 */
export function stipple(count: number, width: number, height: number, seed = 7): Dot[] {
	const next = lcg(seed);
	const dots: Dot[] = [];
	while (dots.length < count) {
		const t = next();
		const crest = moundProfile(t);
		// Bias towards the base: `1 - sqrt(U)` has a density that falls off
		// linearly with height, so the crest dissolves and the base is solid.
		const u = 1 - Math.sqrt(next());
		const h = u * crest;
		// Thin the crest out so the top dissolves into the paper.
		if (next() > 0.25 + 0.75 * (1 - h / Math.max(crest, 1e-6)) ** 0.6 && h > crest * 0.8) continue;
		dots.push({
			x: Math.round(t * width * 10) / 10,
			y: Math.round((height - h * height) * 10) / 10,
			r: Math.round((0.55 + 0.9 * (1 - u)) * 10) / 10
		});
	}
	return dots;
}
