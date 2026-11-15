# Anti-Lethe

**A public drift register for AI model behaviour.**

The Internet Archive runs a project called *Ask Me Twice*: it asks the same
curated questions of the same models every single day and keeps every answer.
Anti-Lethe reads that archive and reports how the answers changed — and, more
importantly, **why**.

---

## The one idea

When an archived answer changes, there are three possible causes. Reporting them
as a single "drift" number would be meaningless, so this project never does.

| | What changed | What it means |
|---|---|---|
| **stable** | Nothing. Same model build, same serving host. | Sampling noise: the same system answering the same question twice. **This is the baseline everything else is measured against.** |
| **provider** | The serving host. Same build. | *Ask Me Twice* routes through OpenRouter, so an open-weight model can be served by Novita one day and DeepInfra the next. Quantisation and serving stack change. **The model does not.** |
| **version** | The model build. | The vendor repointed a model-id alias at new weights (`anthropic/claude-sonnet-5` → `anthropic/claude-sonnet-5-20260630`). This is the only category where a difference is unambiguously the model changing, and it is detected by **exact string comparison**, carrying zero statistical uncertainty. |

Every aggregate the backend computes is stratified by these three. The frontend's
whole job is to make that stratification legible to someone who is not a
statistician.

The two headline numbers are ratios against the noise floor:

- **host effect** = `provider_mean / stable_mean` — how many times further an
  answer moves when only the inference host changed.
- **rebuild effect** = `version_mean / stable_mean` — the same for a new build.

A stratum with no observations has **no ratio**. It is reported as `null` and
rendered as an em dash, never as zero. "We did not observe this" and "this did
not happen" are different claims, and the second one is never made on the first
one's behalf.

### A note on the serving host

The critical field is `turns[0].provider`, which is the **inference host**
(`"Novita"`, `"DeepInfra"`, `"StreamLake"`). The response also has a top-level
`provider` field, which is the **vendor** (`"openai"`). Conflating the two would
collapse the provider and version strata into each other, which is the single
mistake this project exists to avoid.

---

## Quickstart

Works from a clean clone. No API key needed.

```bash
git clone https://github.com/anti-lethe/anti-lethe
cd anti-lethe

# 1. the pipeline, in a project-local virtual environment
uv venv --python 3.12
uv pip install -e 'backend[dev]'

# Everything below assumes the venv is active:
#   source .venv/bin/activate      # macOS / Linux
#   .venv\Scripts\activate         # Windows

# 2. read the archive into SQLite (see "Ingest is slow" below)
antilethe ingest --questions are-ai-chatbots-biased,is-climate-change-real

# 3. compute the metrics (every dependency-free method)
antilethe analyze --methods cosine_bow,jaccard_ngram,ncd,markers

# 4. check nothing was altered since it was fetched
antilethe verify

# 5. write the static dataset, switchable between the three measures
antilethe export --out frontend/static/data --methods cosine_bow,jaccard_ngram,ncd

# With the extras installed (uv pip install -e 'backend[all]'), add the
# model-backed methods. They download a model on first use and take a while.
#   antilethe analyze --methods embedding,embedding_map,nli,stance_nli,tokens
#   antilethe export --out frontend/static/data --methods cosine_bow,embedding,nli,ncd,jaccard_ngram

# 6. the site
cd frontend
npm install
npm run dev
```

From the repository root you can skip activation and use `uv run`, which picks
up `./.venv`:

```bash
uv run antilethe analyze
```

One caveat worth knowing: **do not use `uv run` from inside `backend/`**. That
directory has its own `pyproject.toml`, so uv treats it as a separate project
and builds a second virtual environment there. For the test and type-check
commands, which must run from `backend/`, activate the venv first and call them
directly.

Plain `pip install -e 'backend[dev]'` also works, but it installs into whatever
Python is on your PATH. Use a virtual environment.

Without step 2–5 the site still builds and runs: it shows a designed "the dataset
has not been built" state. It never shows zeros standing in for missing data.

### Ingest is slow, and here is why

Upstream throttles anonymous readers **per connection**, and the rate moves:
measured at roughly 22 KB/s in October 2026, 420 KB/s in early November, and
under 10 KB/s a week later. A single day's bulk export is about 25 MB, because
each record carries the model's encrypted reasoning blobs, so a full
137-question backfill of some 120 days is anywhere from half an hour to most
of a day depending on which throttle you meet. The export endpoint ignores
range requests, so a dropped download restarts from zero.

Two things make this workable:

- **The throttle is per connection, not per account.** `--concurrency N` fetches
  N days (or N series) at once and multiplies effective throughput; twelve
  connections at 9 KB/s each is still 108 KB/s. Upstream accepts about **twenty
  concurrent connections per address** and refuses the rest outright, so keep
  `N` at 12 to 16: a 32-connection run lands twenty days per batch and fails
  the other twelve on the first connect, and a stalled connection's retry is
  refused too while the others hold the slots. Failed days are simply fetched
  again by the next `ingest` over the same range, which skips complete days.
- **`--questions` fetches depth instead of width.** One `(question, model)`
  series is a single small request covering *every* day the archive holds. A
  handful of questions across all models and all days costs minutes, where the
  same number of complete days costs hours. The result is a deliberately partial
  archive — full history for the questions you chose, nothing for the others —
  and days are not marked complete, so a later full ingest still fetches them.

```bash
# deep and narrow: a few questions, every day, minutes
antilethe ingest --questions are-ai-chatbots-biased,is-climate-change-real

# wide: every question, whole days from the bulk export, one request per day
antilethe ingest --since 2026-07-18 --until 2026-11-11 --concurrency 12

# with a key the request-rate limit rises from 30/min to 120/min
AMT_KEY=... antilethe ingest
```

---

## Commands

```
antilethe ingest   [--since DATE] [--until DATE] [--questions a,b,c]
                   [--force] [--concurrency N] [--db PATH]
antilethe analyze  [--methods cosine_bow,markers,ncd,jaccard_ngram] [--rebuild]
antilethe export   --out ../frontend/static/data [--methods cosine_bow,ncd,embedding]
                   [--no-shard-snapshots]
antilethe verify   [--day DATE]
antilethe serve    [--host 0.0.0.0] [--port 8000] [--reload]
antilethe methods  # what is installed, and what each one can see
```

`analyze` is incremental: a transition or answer already scored under the same
method and version is skipped, so a daily run costs one day's pairs and an
interrupted model-backed pass resumes where it stopped. `--rebuild` deletes a
method's output first and recomputes it all, which is the right call after a
day is backfilled *between* two days already stored.

Everything exits non-zero on failure. There is no mode in which a broken
upstream, an empty archive or a broken ledger produces a dataset anyway.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ GitHub Actions (daily + manual dispatch)                         │
│                                                                  │
│   antilethe ingest   → SQLite (raw archive, append-only)         │
│   antilethe analyze  → distances + features, per method+version  │
│   antilethe verify   → fails the run on a broken ledger          │
│   antilethe export   → static JSON shards                        │
│                          │                                       │
└──────────────────────────┼───────────────────────────────────────┘
                           ▼
                  frontend/static/data/*.json
                           │
                  SvelteKit build (adapter-static)
                           ▼
                  GitHub Pages  ← the published site, no backend
```

**The published site is fully static.** It fetches JSON from its own origin. No
CORS, no API key in the browser, no runtime backend, no cost. The only external
requests are to Google Fonts.

**FastAPI serves the same computed data** for local exploration and for anyone
self-hosting. Point the frontend at it with `PUBLIC_API_BASE`; the site must and
does work correctly with that unset, which is how it is published.

All analysis is Python, so adding a drift method is one new file in
`backend/src/antilethe/analysis/methods/` and nothing else changes.

### Why the pipeline splits in two

`analyze` compares text, so it is the expensive half, and it persists its output
into the `distances` and `features` tables keyed by method name **and version**.
`build_index` reads those tables and assembles the dataset.

The static exporter and every API route both call `build_index` through one
serialiser. That is what makes `/api/v1/summary` byte-identical to the matching
slice of `index.json`, rather than two implementations that agree today.

---

## Adding an analysis method

One file, one decorator. The registry handles the rest: the method appears in
`antilethe methods`, in `--methods`, in the manifest and on the site's method
page without another line of code.

```python
# backend/src/antilethe/analysis/methods/length_delta.py
"""Relative change in answer length."""

from ..registry import pairwise


@pairwise(
    "length_delta",
    version="1.0.0",
    description="Relative change in answer length. Catches truncation.",
)
def length_delta(prev_text: str, next_text: str) -> float:
    """Return |Δlength| / longest, in [0, 1]."""
    longest = max(len(prev_text), len(next_text), 1)
    return abs(len(prev_text) - len(next_text)) / longest
```

Then add it to `methods/__init__.py` so the decorator runs:

```python
from . import cosine_bow, length_delta, markers
```

```bash
antilethe analyze --methods length_delta
antilethe export --out frontend/static/data --method length_delta
```

Use `@feature` instead for a per-response measurement returning
`dict[str, float]`. Declare `requires=("some-package",)` for an optional
dependency: the method is then silently excluded when it is not installed, and
asking for it by name is a hard error naming the extra to install.

### The shipped methods

Four need nothing installed. Five more need an optional extra and a model
download, and are the ones that say something about *meaning*.

| Method | Kind | Extra | What it sees, and what it misses |
|---|---|---|---|
| `cosine_bow` | pairwise | — | Cosine over word frequencies. **Default.** Any reader can verify a number by hand. Cannot tell a reversal from a rewording: "X is safe" and "X is not safe" score as nearly identical. |
| `jaccard_ngram` | pairwise | — | Jaccard distance over word-trigram shingles (Broder 1997). Sees word order and phrase reuse that a bag of words cannot; still a surface measure. |
| `ncd` | pairwise | — | Normalised compression distance (Cilibrasi & Vitányi 2005). Parameter-free; sees shared structure and sentence order. Blind to negation like the others above. |
| `markers` | feature | — | Refusal, hedging, stance, length, citations. Lexical probes, every regex in one auditable module. |
| `embedding` | pairwise | `embedding` | Cosine between BGE sentence embeddings. Sees paraphrase that word frequencies miss. Still weak on negation. |
| `embedding_map` | feature | `embedding` | The first two principal components of a question's answer embeddings: each answer's position in that question's plane, drawn as a trajectory on the compare page. |
| `nli` | pairwise | `nli` | `P(contradiction)`, the larger of both orderings, from a DeBERTa cross-encoder trained on ANLI. **The method that actually detects reversals.** |
| `stance_nli` | feature | `nli` | Zero-shot stance probe (Yin et al. 2019): `P(yes)`, `P(no)`, `P(declines)` by entailment against three fixed hypotheses. Tracks *which way* a polar question was answered. |
| `tokens` | feature | `tokens` | Length in a fixed public tokenizer (`cl100k_base`), comparable across every model, plus characters per token as a formatting-shift signal. |

`cosine_bow` is the default precisely because it is weak in a knowable way. It
is reported alongside the stance and refusal markers for that reason, and the
site can switch the whole register to any other exported pairwise measure.

Three aggregates sit on top of whichever measure is selected:

- **Within-model ratios.** The pooled host effect divides one population of
  pairs by another, and the populations are different models: switches happen
  almost only to open-weight models. If those are steadier day to day than the
  first-party models that never switch, the pooled ratio can fall below one
  while every individual model's sits above it — which is exactly what the
  embedding measure showed. So each ratio is also taken inside every model and
  reported as a median with quartiles, and the site leads with that.
- **Bootstrap intervals** on the two pooled ratios (percentile bootstrap,
  1000 resamples, fixed seed). A ratio whose interval includes 1× is reported
  as indistinguishable from noise, in words.
- **Change points** per model: binary segmentation with a least-absolute-
  deviations cost and a BIC-style penalty over the model's daily mean distance.
  Each break is joined to the event log, so it reads as *explained by a host
  switch*, *explained by a rebuild*, or *unexplained* — and unexplained is the
  finding.
- **Coverage**: the number of questions that actually have a series, stated
  separately from the catalogue size everywhere the site counts questions; and,
  per measure, the number of questions that measure was actually run over
  (`span.measured_questions`), because a costly measure may cover a subset.
- **Adjacent days only.** Upstream does not run every model every day: since
  late October 2026 eight models answer daily and the rest rotate, appearing
  every few days. A transition pairs an answer with the model's previous
  *available* answer, so a rotating model's "day-to-day" distance spans three
  or four days, and that is not the quantity the noise floor describes. The
  noise floor, the three strata and the within-model ratios are therefore
  computed over adjacent-day transitions only. Gapped transitions still drive
  the per-day views, and `gaps` in `index.json` counts how many were set aside
  and the longest gap, so the exclusion is visible rather than silent.

### Running the model-backed methods: GPU, CPU, and the fast profile

The defaults are the accurate checkpoints (`BAAI/bge-base-en-v1.5`,
`MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`). The methods use a GPU when
the installed `torch` can see one, in float32 on either device, so a distance
computed on a GPU is the same number as one computed on a CPU. Measured on an
RTX 2060 against the same laptop's CPU:

| checkpoint | CPU | GPU |
|---|---|---|
| `bge-small-en-v1.5` | 6.5 texts/s | 95 texts/s |
| `bge-base-en-v1.5` | 1.2 texts/s | 35 texts/s |
| `nli-MiniLM2-L6-H768` | 3.8 pairs/s | 64 pairs/s |
| `DeBERTa-v3-base-mnli-fever-anli` | 0.07 pairs/s | 46 pairs/s |

On a CPU the DeBERTa default makes a full NLI pass a matter of weeks, so a
*fast profile* exists that trades accuracy for roughly fifty times the
throughput:

```bash
ANTILETHE_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 \
ANTILETHE_NLI_MODEL=cross-encoder/nli-MiniLM2-L6-H768 \
ANTILETHE_NLI_MAX_CHARS=1500 \
antilethe analyze --methods embedding,embedding_map,nli,stance_nli,tokens
```

The published dataset mixes the two on purpose: embeddings under the small
BGE encoder, where the difference is minor, and `nli` and `stance_nli` under
the DeBERTa default on a GPU, because detecting reversals is the one job
where the adversarially trained model earns its cost. On the stance probe
DeBERTa assigns the settled question "is climate change real" a median
`P(no)` of 0.004 where MiniLM assigned 0.25. Whichever checkpoint ran is
recorded per method in `manifest.json` (`methods_installed[].model`) and shown
on the site's method page, so a distance under one encoder is never mistaken
for a distance under another.

To install the CUDA build of `torch` into the project venv, without touching
anything global:

```bash
uv pip install --reinstall-package torch "torch>=2.14,<2.15" \
  --extra-index-url https://download.pytorch.org/whl/cu126
```

### On a rented GPU: the job image

A laptop GPU does the full-archive DeBERTa passes in about eight hours; an A100
or a 4090 does them in well under one. The repository therefore ships the
model-backed passes as a self-contained job container, built by the
`gpu-image` workflow and published to `ghcr.io/<owner>/<repo>/gpu:latest`.
One run of the container does everything: download the archive seed from the
`archive` release, run the requested `analyze` steps on the GPU, verify the
ledger, gzip the archive and upload it back to the release (replacing the
asset), then, on RunPod, terminate its own pod so billing stops. Nothing is
installed on the box and nothing has to be copied by hand; the `pipeline`
workflow picks the new seed up on its next run with an empty cache, and a
developer machine gets it with `gh release download archive`.

```bash
# anywhere with Docker and an NVIDIA GPU
docker run --rm --gpus all   -e GH_TOKEN=<token with repo scope>   -e GITHUB_REPOSITORY=<owner>/<repo>   ghcr.io/<owner>/<repo>/gpu:latest
```

On RunPod: *Deploy a Pod → GPU (an A40 or a 4090 is plenty; 50 GB of disk) →
Edit template → Container image* `ghcr.io/<owner>/<repo>/gpu:latest`, and
under *Environment variables* set `GH_TOKEN`, `GITHUB_REPOSITORY` and, so the
pod shuts itself down when finished, `RUNPOD_API_KEY` (`RUNPOD_POD_ID` is set
by RunPod). The container has no web endpoint; it is a batch job whose result
is the release asset, and its progress is the pod's log. If the GHCR package
is private, make it public (it holds only this repository's code) or give the
template registry credentials.

| variable | default | meaning |
|---|---|---|
| `GH_TOKEN` | required | reads the seed release, writes the result asset |
| `GITHUB_REPOSITORY` | `tewodros18/the-anti-lethe-machine` | which repository's releases |
| `SEED_TAG` / `RESULT_TAG` | `archive` / same as seed | where the archive comes from and goes to |
| `ANALYZE_STEPS` | `nli;stance_nli --rebuild` | `;`-separated `analyze --methods` argument lists, run in order |
| `ANTILETHE_*` | embedding model `bge-small`, batch sizes 128 / 64 | any pipeline setting |

The default steps finish an interrupted `nli` pass incrementally and rebuild
`stance_nli` under the DeBERTa default, which is the state the published seed
was left in. Give `ANALYZE_STEPS` the value `embedding,embedding_map;nli
--rebuild;stance_nli --rebuild` for a from-scratch recomputation of every
model-backed measure.

### A method that needs the whole series

Methods backed by a model should not encode two texts at a time. Register a
``prepare`` hook and it is called once per question with every answer in that
series, before the method is applied to any pair:

```python
@pairwise("embedding", version="2.0.0", requires=("sentence-transformers",), prepare=prepare)
```

A method that needs the whole series to mean anything at all — a projection of
the answer space — can only exist because of this hook.

---

## Data contract

```
static/data/
├── index.json                  # everything except snapshot text
├── manifest.json               # build provenance, plus every day's Merkle root
└── snapshots/
    └── {question_slug}.json    # all models × kept days for one question
```

`index.json` carries the span, the global noise floor, the timeline, the
decomposition, per-model fingerprints, instability cells, the event lists and the
price history. Snapshots are fetched per question on demand.

Snapshot days are the first day, the last day, every 7th day, **every event day,
and the day immediately before it** — so every comparison the UI points at is
always present.

The pydantic models in `backend/src/antilethe/models.py` are the contract. The
TypeScript interfaces in `frontend/src/lib/data/types.ts` mirror them
field-for-field, and `backend/tests/test_contract.py` enforces that in both
directions by parsing `types.ts` and comparing field names, then validating the
exported JSON against a JSON Schema generated from the models. A field added to
one side and not the other fails CI.

### The ledger

`ledger.py` builds a SHA-256 Merkle tree over each day's answer hashes and chains
each day's root to the previous day's.

> This ledger proves that a record has not been altered since it was fetched. It
> does not and cannot prove that a given model produced it. Provenance rests on
> the Internet Archive's operation of the upstream archive, not on cryptography.

`antilethe verify` recomputes every root from the rows now in the database,
**re-hashing each answer from its text** rather than trusting the stored digest,
and exits non-zero on any mismatch.

---

## Deployment

### GitHub Pages (the published site)

`.github/workflows/pipeline.yml` runs daily at 17:00 UTC and on manual
dispatch: top up the archive → analyze → verify → export → build → deploy.
Permissions are `contents: read`, `pages: write`, `id-token: write`.

It is built around *not* downloading history, because upstream throttles
anonymous readers, at times to under 10 KB/s per connection. It carries the
archive between runs in the Actions cache, seeds it from a release asset when
the cache is empty, and each day fetches only the last few days' bulk exports,
one request and a minute or so per day. A repository variable switches it to a
cheaper deep-questions mode that keeps full history for a handful of
questions only.

#### Publishing it, step by step

1. **Push the repository** to GitHub (public, for a free Pages site).

   ```bash
   git remote add origin https://github.com/<you>/anti-lethe.git
   git push -u origin main
   ```

2. **Enable Pages from Actions**: repository *Settings → Pages → Build and
   deployment → Source: GitHub Actions*. Nothing else; the workflow deploys.

3. **Seed the archive** so the first run does not start from nothing. Create a
   release tagged `archive` and attach your local archive to it (web UI:
   *Releases → Draft a new release*, tag `archive`, drag the file in; or
   `gh release create archive <files>`). The workflow downloads it whenever
   the cache is empty. Release assets are capped at 2 GB each, so a full
   archive goes up compressed and, if still too large, in parts; the workflow
   reassembles either form:

   ```bash
   gzip -9 -k data/archive.db                      # -> data/archive.db.gz
   split -b 1900m data/archive.db.gz data/archive.db.gz.part-   # only if > 2 GB
   ```

   Attach `archive.db`, or `archive.db.gz`, or the `archive.db.gz.part-*`
   files. Without a seed the first run starts from an empty archive and
   fetches only the last few days, so the register begins thin and deepens
   daily.

4. **Choose what the daily run does**, with repository variables (*Settings →
   Secrets and variables → Actions → Variables*), all optional:

   | variable | default | meaning |
   |---|---|---|
   | `ANTILETHE_DAYS_BACK` | `4` | whole-day mode: how many recent days to re-read each run, so a day still filling in upstream is completed later |
   | `ANTILETHE_QUESTIONS` | unset | set to comma-separated slugs to switch to deep-questions mode: only those questions, full history, topped up newest-first |
   | `ANTILETHE_EXPORT_METHODS` | `cosine_bow,jaccard_ngram,ncd` | measures the site can switch between; each must have distances in the archive |
   | `ANTILETHE_MODEL_METHODS` | unset | opt in to model-backed methods on the runner, realistically `embedding,embedding_map` only; see below |

   And one optional secret, `AMT_KEY`, if the Internet Archive gives you one:
   it raises the request budget from 30/min to 120/min.

5. **Run it once by hand**: *Actions → pipeline → Run workflow*. The site is
   at `https://<you>.github.io/anti-lethe/` when the deploy step finishes.
   After that it runs itself daily.

#### The model-backed measures and the public site

The runner has two cores and no GPU, so by default the daily run computes
only the dependency-free measures and the site switches between those. The
model-backed measures come from the seed: run them on a machine with a GPU
(see *Running the model-backed methods*), upload the resulting archive as the
`archive` release, and list them in `ANTILETHE_EXPORT_METHODS`. The daily run
then keeps the cheap measures current to the day and re-exports the
model-backed ones from the seeded distances, which lag until the seed is
refreshed; each measure's index states how many questions it covers, and
`manifest.json` records which checkpoint produced it.

Because analysis is incremental, a day's new embeddings are cheap enough for
the runner: set `ANTILETHE_MODEL_METHODS` to `embedding,embedding_map` and it
encodes only the new answers each run with the small BGE encoder the workflow
pins. Do not add `nli` or `stance_nli` there: the seed's distances are from
the DeBERTa default, which is far too slow on the runner's CPU, and a method
must not mix checkpoints. The workflow pins the embedding checkpoint and
leaves the NLI one at its default precisely so that what the runner computes
and what the seed holds are recorded identically.

`BASE_PATH` is set by the workflow to `/<repository name>`; every internal
link and data fetch goes through it, which is the one thing that breaks a
Pages subpath deployment when wrong. For a user or organisation site served
from the root, leave it unset.

### The API (optional)

GitHub Pages cannot run FastAPI, and **the site is complete without it**. For a
live API the free options are Hugging Face Spaces (Docker SDK), Fly.io or Render.
`backend/Dockerfile` makes it one command:

```bash
docker build -t antilethe-api backend
docker run -p 8000:8000 -v "$PWD/data:/data" antilethe-api
# http://localhost:8000/docs
```

---

## Limitations

These are not caveats on the numbers. They are the boundary of what the numbers
mean, and they are repeated verbatim on the site's method page.

1. **One sample per day.** The archive records a single answer per question per
   model per day. A model that answers differently on two attempts within one day
   is indistinguishable here from one that drifted overnight. Every distance is a
   lower bound on the variation the model is capable of.

2. **Routed through OpenRouter, not direct.** What is observed is a model as
   served by whichever host OpenRouter selected, including that host's
   quantisation and serving stack. A vendor's own API might answer differently on
   the same day with the same weights.

3. **Word frequencies, not meaning.** The default distance counts words. It
   cannot distinguish a reversal from a rewording. The marker probes sit beside
   it for this reason, and `nli` is the method that actually detects reversals.

4. **Sampling parameters are unrecorded.** Temperature, top-p, seed and system
   prompt are not captured upstream. A change in any of them appears here as
   drift, and there is no way from this data to rule that out. The stable stratum
   absorbs it into what is reported as noise.

5. **Hashes prove custody, not origin.** The ledger shows a record has not been
   altered since it was fetched. It cannot show which model produced it.

6. **The probe set is public, and therefore contaminable.** The questions are
   published and stable, so they can be trained on, cached or special-cased. A
   model that became more consistent on these specific questions has not
   necessarily become more consistent in general, and this register cannot tell
   the difference.

---

## Development

```bash
# backend — activate the venv first, then run these from backend/
uv venv --python 3.12
uv pip install -e 'backend[dev]'
source .venv/bin/activate      # .venv\Scripts\activate on Windows
cd backend
pytest                         # ≥80% coverage enforced
mypy --strict src              # must run from backend/ to read its pyproject.toml
ruff check . && ruff format --check .

# frontend
cd frontend
npm install
npm run check                # svelte-check
npx vitest run
npm run lint
npm run build
```

Svelte 5 runes only: `$state`, `$derived`, `$props`, `$effect` and snippets. No
`export let`, no `$:`, no `svelte/store` for component state.

Fabricated data exists in exactly one place, `backend/tests/fixtures/` and
`backend/tests/sample_archive.py`, and is never importable from application code.
CI greps the repository to enforce it.

---

## Non-goals

No user accounts. No database other than SQLite. No server-side rendering of
dynamic data. No live calls to the upstream API from the browser. No CSS
framework. No second charting library beside LayerCake, and no full `d3` — only
the `d3-scale`, `d3-shape` and `d3-array` submodules actually used. Nothing
writes back to the upstream archive, and no model inference happens anywhere in
the request path.

---

## Licence

MIT. See [LICENSE](LICENSE).

The underlying data is the Internet Archive's. This project measures archived
text; it does not redistribute the archive.

## Citation

```bibtex
@software{antilethe,
  title  = {Anti-Lethe: a public drift register for AI model behaviour},
  year   = {2026},
  url    = {https://github.com/anti-lethe/anti-lethe},
  note   = {Stratifies observed change in archived model answers into sampling
            noise, inference-host change, and model rebuild.}
}
```

Built on the Internet Archive's *Ask Me Twice* archive.
