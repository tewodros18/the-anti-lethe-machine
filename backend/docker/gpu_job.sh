#!/usr/bin/env bash
# The GPU job: seed -> analyze -> verify -> upload. Runs to completion and exits;
# on RunPod it can also terminate its own pod so billing stops.
#
# Required:
#   GH_TOKEN             token with read/write on the repository's releases
# Optional:
#   GITHUB_REPOSITORY    owner/repo                    (default: tewodros18/the-anti-lethe-machine)
#   SEED_TAG             release holding archive.db*   (default: archive)
#   RESULT_TAG           release to upload to          (default: same as SEED_TAG; asset replaced)
#   ANALYZE_STEPS        ';'-separated analyze argument lists
#                        (default: "nli;stance_nli --rebuild")
#   ANTILETHE_*          any pipeline setting, e.g. ANTILETHE_EMBEDDING_MODEL
#   RUNPOD_API_KEY       with RUNPOD_POD_ID (set by RunPod): terminate the pod at the end
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required (release download and upload)}"
REPO="${GITHUB_REPOSITORY:-tewodros18/the-anti-lethe-machine}"
SEED_TAG="${SEED_TAG:-archive}"
RESULT_TAG="${RESULT_TAG:-$SEED_TAG}"
STEPS="${ANALYZE_STEPS:-nli;stance_nli --rebuild}"
export ANTILETHE_EMBEDDING_MODEL="${ANTILETHE_EMBEDDING_MODEL:-BAAI/bge-small-en-v1.5}"
export ANTILETHE_EMBEDDING_BATCH_SIZE="${ANTILETHE_EMBEDDING_BATCH_SIZE:-128}"
export ANTILETHE_NLI_BATCH_SIZE="${ANTILETHE_NLI_BATCH_SIZE:-64}"

stamp() { printf '=== %s  %s\n' "$1" "$(date -u +%FT%TZ)"; }

stamp "gpu job start"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "no GPU visible; this will be slow"
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

mkdir -p data
if [ ! -f data/archive.db ]; then
  stamp "download seed $REPO@$SEED_TAG"
  gh release download "$SEED_TAG" --repo "$REPO" --pattern 'archive.db*' --dir data
  ( cd data
    if ls archive.db.gz.part-* >/dev/null 2>&1; then cat archive.db.gz.part-* > archive.db.gz && rm archive.db.gz.part-*; fi
    if [ -f archive.db.gz ]; then gzip -d archive.db.gz; fi
    ls -la )
else
  stamp "using existing data/archive.db"
fi

IFS=';' read -ra STEP_LIST <<< "$STEPS"
for step in "${STEP_LIST[@]}"; do
  step="$(echo "$step" | xargs)"; [ -z "$step" ] && continue
  stamp "analyze $step"
  # shellcheck disable=SC2086
  antilethe analyze --methods $step
done

stamp "verify"
antilethe verify

stamp "pack"
rm -f data/archive.db.gz data/archive.db.gz.part-*
python -c "import sqlite3; c=sqlite3.connect('data/archive.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
gzip -6 -c data/archive.db > data/archive.db.gz
sha256sum data/archive.db.gz | tee data/archive.db.gz.sha256
size=$(stat -c %s data/archive.db.gz)
assets=(data/archive.db.gz)
if [ "$size" -gt 1900000000 ]; then
  ( cd data && split -b 1900m -d --additional-suffix= archive.db.gz archive.db.gz.part- )
  assets=(data/archive.db.gz.part-*)
fi

stamp "upload to $REPO@$RESULT_TAG"
if ! gh release view "$RESULT_TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$RESULT_TAG" --repo "$REPO" --title "Archive ($RESULT_TAG)" --notes "Uploaded by the GPU job on $(date -u +%F)." --latest=false
fi
# A whole-file asset and a split set must not coexist: the pipeline's seed step would read both.
for old in $(gh release view "$RESULT_TAG" --repo "$REPO" --json assets -q '.assets[].name' | grep -E '^archive\.db'); do
  gh release delete-asset "$RESULT_TAG" "$old" --repo "$REPO" --yes || true
done
gh release upload "$RESULT_TAG" "${assets[@]}" data/archive.db.gz.sha256 --repo "$REPO" --clobber
stamp "uploaded $(printf '%s ' "${assets[@]##*/}")"

if [ -n "${RUNPOD_API_KEY:-}" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
  stamp "terminating pod $RUNPOD_POD_ID"
  curl -fsS -X POST "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" \
    -H 'content-type: application/json' \
    -d "{\"query\":\"mutation { podTerminate(input: {podId: \\\"$RUNPOD_POD_ID\\\"}) }\"}" || echo "pod terminate call failed; stop it from the console"
fi
stamp "gpu job done"
