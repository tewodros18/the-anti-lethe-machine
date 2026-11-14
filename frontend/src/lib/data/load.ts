/**
 * Fetching and validating the dataset shards.
 *
 * Two rules shape this module.
 *
 * Everything is fetched from the site's own origin under `base`, because the
 * published site is static and served from a subpath on GitHub Pages. An
 * optional `PUBLIC_API_BASE` points the same loader at a self-hosted FastAPI,
 * but the site must work correctly with it unset, which is how it ships.
 *
 * A shard that is missing or malformed raises `DatasetError`. It never
 * degrades into an empty dataset, because an empty dataset renders as zeros
 * and zeros here would be invented findings.
 */

import { base } from '$app/paths';
import { PUBLIC_API_BASE } from '$env/static/public';
import type { Index, Manifest, SnapshotShard } from './types';

/** Thrown when a shard is absent or fails validation. */
export class DatasetError extends Error {
	readonly cause?: unknown;

	constructor(message: string, cause?: unknown) {
		super(message);
		this.name = 'DatasetError';
		this.cause = cause;
	}
}

/** True when the build was pointed at a live API rather than static shards. */
export const usingApi = Boolean(PUBLIC_API_BASE);

/** Where a static shard lives. */
function dataUrl(path: string): string {
	return `${base}/data/${path}`;
}

/** The matching API route, used only when `PUBLIC_API_BASE` is set. */
function apiUrl(path: string): string {
	return `${PUBLIC_API_BASE.replace(/\/$/, '')}/api/v1/${path}`;
}

async function getJson(url: string, what: string): Promise<unknown> {
	let response: Response;
	try {
		response = await fetch(url);
	} catch (error) {
		throw new DatasetError(`Could not reach ${what} at ${url}.`, error);
	}
	if (!response.ok) {
		throw new DatasetError(`${what} is not available (HTTP ${response.status} from ${url}).`);
	}
	try {
		return await response.json();
	} catch (error) {
		throw new DatasetError(`${what} at ${url} is not valid JSON.`, error);
	}
}

function requireObject(value: unknown, what: string): Record<string, unknown> {
	if (typeof value !== 'object' || value === null || Array.isArray(value)) {
		throw new DatasetError(`${what} is not a JSON object.`);
	}
	return value as Record<string, unknown>;
}

function requireArray(value: unknown, what: string): unknown[] {
	if (!Array.isArray(value)) {
		throw new DatasetError(`${what} is not an array.`);
	}
	return value;
}

/**
 * Validate the fields the UI actually reads.
 *
 * This is a structural check, not a full schema validation: the backend's
 * pydantic models are the contract, and `tests/test_contract.py` enforces that
 * the exported JSON matches them. The point here is to fail with a sentence a
 * reader can act on rather than to re-implement the schema.
 */
export function validateIndex(payload: unknown): Index {
	const root = requireObject(payload, 'index.json');

	if (root.schema_version !== 1) {
		throw new DatasetError(
			`index.json has schema_version ${String(root.schema_version)}; this site reads version 1.`
		);
	}
	for (const key of [
		'generated_at',
		'method',
		'span',
		'noise',
		'decomposition',
		'questions',
		'snapshot_days'
	]) {
		if (!(key in root)) {
			throw new DatasetError(`index.json is missing "${key}".`);
		}
	}
	for (const key of [
		'timeline',
		'models',
		'cells',
		'version_events',
		'provider_events',
		'price_changes',
		'changepoints'
	]) {
		requireArray(root[key], `index.json "${key}"`);
	}
	return root as unknown as Index;
}

export function validateManifest(payload: unknown): Manifest {
	const root = requireObject(payload, 'manifest.json');
	if (root.schema_version !== 1) {
		throw new DatasetError(
			`manifest.json has schema_version ${String(root.schema_version)}; this site reads version 1.`
		);
	}
	requireArray(root.methods_installed, 'manifest.json "methods_installed"');
	return root as unknown as Manifest;
}

export function validateShard(payload: unknown, slug: string): SnapshotShard {
	const root = requireObject(payload, `snapshots/${slug}.json`);
	if (typeof root.question_slug !== 'string') {
		throw new DatasetError(`snapshots/${slug}.json is missing "question_slug".`);
	}
	requireObject(root.models, `snapshots/${slug}.json "models"`);
	return root as unknown as SnapshotShard;
}

export async function loadIndex(): Promise<Index> {
	const url = usingApi ? apiUrl('index') : dataUrl('index.json');
	return validateIndex(await getJson(url, 'The dataset (index.json)'));
}

/** The full index as computed by one named pairwise method. */
export async function loadMethodIndex(method: string): Promise<Index> {
	const url = usingApi
		? `${apiUrl('index')}?method=${encodeURIComponent(method)}`
		: dataUrl(`methods/${encodeURIComponent(method)}.json`);
	return validateIndex(await getJson(url, `The dataset under "${method}"`));
}

export async function loadManifest(): Promise<Manifest> {
	const url = usingApi ? apiUrl('manifest') : dataUrl('manifest.json');
	return validateManifest(await getJson(url, 'The build manifest'));
}

export async function loadShard(slug: string): Promise<SnapshotShard> {
	const url = usingApi ? apiUrl(`snapshots/${slug}`) : dataUrl(`snapshots/${slug}.json`);
	return validateShard(await getJson(url, `Snapshots for "${slug}"`), slug);
}
