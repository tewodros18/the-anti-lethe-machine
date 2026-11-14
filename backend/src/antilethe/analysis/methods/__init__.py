"""Every method module is imported here so its decorator runs.

Adding a method means adding a file and one line to this list. The optional
methods are imported defensively: their dependencies may be absent, in which
case the registry simply never learns about them and the pipeline is unaffected.

Shipped, no dependencies:
    cosine_bow     word-frequency cosine, the default; hand-checkable
    jaccard_ngram  trigram-shingle Jaccard; sees word order and phrase reuse
    ncd            normalised compression distance; sees shared structure
    markers        refusal / hedging / stance / length probes, all regex

Optional extras:
    embedding      sentence-embedding cosine            [embedding]
    embedding_map  2-D PCA of a question's answer space  [embedding]
    nli            P(contradiction), both orderings      [nli]
    stance_nli     zero-shot yes / no / declines probe   [nli]
    tokens         length in a fixed public tokenizer    [tokens]
"""

from __future__ import annotations

from . import cosine_bow, jaccard_ngram, markers, ncd

__all__ = ["cosine_bow", "jaccard_ngram", "markers", "ncd"]

# Optional extras. A missing dependency must not break a run, so registration
# is attempted and the method is silently absent if its imports fail.
try:  # pragma: no cover - depends on optional extras
    from . import embedding  # noqa: F401  (registers on import)

    __all__.append("embedding")
except ImportError:  # pragma: no cover
    pass

try:  # pragma: no cover - depends on optional extras
    from . import nli, stance_nli  # noqa: F401  (registers on import)

    __all__.extend(["nli", "stance_nli"])
except ImportError:  # pragma: no cover
    pass

try:  # pragma: no cover - depends on optional extras
    from . import tokens  # noqa: F401  (registers on import)

    __all__.append("tokens")
except ImportError:  # pragma: no cover
    pass
