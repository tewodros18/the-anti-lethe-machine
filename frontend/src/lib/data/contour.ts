/**
 * A deterministic contour field: nested rings around one centre that drift
 * further out of round the further they sit from it.
 *
 * Used for the hero illustration. The innermost ring is nearly a circle, the
 * outer ones bend and lean, which is the register's subject drawn as a shape:
 * a fixed mark, and readings that wander the longer they run. The generator is
 * seeded so the drawing is the same on every render and on every machine;
 * nothing about it is random at run time, which also keeps server and client
 * markup identical.
 */

export interface Ring {
	/** Ring index from the centre, 0 first. */
	k: number;
	/** How far out of round the ring is, 0 at the centre to 1 at the edge. */
	drift: number;
	/** SVG path data for a closed polyline. */
	d: string;
}

/** Park–Miller minimal standard generator; enough for phases on a page. */
function lcg(seed: number): () => number {
	let state = seed % 2147483647;
	if (state <= 0) state += 2147483646;
	return () => {
		state = (state * 16807) % 2147483647;
		return (state - 1) / 2147483646;
	};
}

/**
 * Radius multiplier at angle `theta` for a ring with the given `drift`: three
 * low harmonics whose amplitude grows with drift, so the inner rings stay
 * round and the outer ones lean.
 */
export function wobble(
	theta: number,
	drift: number,
	phases: readonly [number, number, number]
): number {
	return (
		1 +
		drift *
			(0.11 * Math.sin(2 * theta + phases[0]) +
				0.07 * Math.sin(3 * theta + phases[1]) +
				0.04 * Math.sin(5 * theta + phases[2]))
	);
}

export interface ContourOptions {
	count: number;
	cx: number;
	cy: number;
	/** Radius of the innermost ring. */
	r0: number;
	/** Spacing between rings. */
	step: number;
	seed?: number;
	/** Vertices per ring. */
	points?: number;
}

/**
 * The rings, innermost first. Each ring's centre also slides a little away
 * from the shared centre as drift grows, so the field leans rather than
 * merely ripples.
 */
export function contours({
	count,
	cx,
	cy,
	r0,
	step,
	seed = 7,
	points = 180
}: ContourOptions): Ring[] {
	const next = lcg(seed);
	const phases: [number, number, number] = [
		next() * 2 * Math.PI,
		next() * 2 * Math.PI,
		next() * 2 * Math.PI
	];
	const lean = (next() - 0.5) * 2;
	const rings: Ring[] = [];
	for (let k = 0; k < count; k++) {
		const drift = count > 1 ? (k / (count - 1)) ** 1.4 : 0;
		const r = r0 + k * step;
		const ox = cx + lean * drift * step * 2.2;
		const oy = cy + drift * step * 0.8;
		const parts: string[] = [];
		for (let i = 0; i < points; i++) {
			const theta = (i / points) * 2 * Math.PI;
			const rr = r * wobble(theta, drift, phases);
			const x = Math.round((ox + rr * Math.cos(theta)) * 10) / 10;
			const y = Math.round((oy + rr * Math.sin(theta)) * 10) / 10;
			parts.push(`${i === 0 ? 'M' : 'L'}${x} ${y}`);
		}
		rings.push({ k, drift, d: parts.join(' ') + ' Z' });
	}
	return rings;
}
