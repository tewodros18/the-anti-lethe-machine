"""Environment-driven configuration.

Every knob the pipeline needs is here. Nothing reads ``os.environ`` directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Anonymous callers get 30 requests/minute on list endpoints; a key raises it to 120.
ANON_RATE_PER_MIN = 30
KEYED_RATE_PER_MIN = 120


class Settings(BaseSettings):
    """Runtime settings, overridable by environment variable or ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="ANTILETHE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- upstream -----------------------------------------------------------
    amt_base_url: str = "https://wayback-api.archive.org/services/amt/api/v1"
    #: Bearer token for the AMT API. Read from ANTILETHE_AMT_KEY or AMT_KEY.
    amt_key: str | None = Field(default=None, validation_alias="AMT_KEY")
    request_timeout: float = 90.0
    #: Stall detector for a bulk read: a day export, or one question series.
    #: This is httpx's per-chunk read timeout, not a total budget: a 25 MB
    #: export trickling in at 10 KB/s for forty minutes never trips it, while a
    #: connection upstream has silently stopped feeding is given up after this
    #: many seconds and retried from the start (the export endpoint does not
    #: resume). Upstream stalls are common enough that a long value here costs
    #: more time than it saves.
    bulk_timeout: float = 120.0
    #: Attempts per request. Backoff doubles from one second and caps at
    #: thirty, so eight attempts ride out a gateway outage of about two
    #: minutes, which is how long its "404 page not found" spells last.
    max_retries: int = 8
    #: Days fetched in parallel. The throttle is per-connection, so this
    #: multiplies effective throughput; it is also the client's request
    #: concurrency bound.
    concurrency: int = 4
    page_size: int = 200
    #: Page size for an incremental series top-up. Small on purpose: the first
    #: page holds the new days plus a few known ones, the second is all known,
    #: and paging stops there.
    incremental_page_size: int = 10
    #: Requests per minute. When unset, derived from whether a key is present.
    rate_limit_per_min: int | None = None
    #: Prefer the gzipped bulk export endpoint (1 request/day) over pagination.
    use_bulk_export: bool = True

    # --- storage ------------------------------------------------------------
    db_path: Path = Path("data/archive.db")

    # --- analysis -----------------------------------------------------------
    default_method: str = "cosine_bow"
    #: Minimum STABLE transitions required before a noise floor is reported.
    min_noise_n: int = 30
    #: Sentence-embedding model for the ``embedding`` and ``embedding_map``
    #: methods. BGE base is a strong general-purpose English encoder that runs
    #: at a usable speed on CPU; ``BAAI/bge-small-en-v1.5`` is the fast option.
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    #: Texts encoded per forward pass by ``prepare``.
    embedding_batch_size: int = 32
    #: NLI cross-encoder for the ``nli`` and ``stance_nli`` methods. This
    #: checkpoint is trained on MNLI, FEVER-NLI and ANLI, which matters: ANLI is
    #: the adversarial set, and it is what makes the model hold up on the
    #: negated and hedged rewordings that real drift looks like.
    nli_model: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    #: Premise/hypothesis pairs scored per forward pass.
    nli_batch_size: int = 16
    #: Characters of each answer the NLI methods read. Attention cost is
    #: quadratic in length, so this is the main speed dial; an answer's
    #: position and core claim sit in its opening, but a reversal buried in a
    #: late paragraph is missed at any truncation.
    nli_max_chars: int = 1500
    #: Characters of answer text kept in a snapshot shard.
    snapshot_chars: int = 4000

    # --- api ----------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so this is settable from one env var."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def effective_rate_per_min(self) -> int:
        """Requests/minute to actually use, honouring the documented limits."""
        if self.rate_limit_per_min is not None:
            return self.rate_limit_per_min
        return KEYED_RATE_PER_MIN if self.amt_key else ANON_RATE_PER_MIN

    @property
    def auth_headers(self) -> dict[str, str]:
        """Authorization header, empty when running anonymously."""
        return {"Authorization": f"Bearer {self.amt_key}"} if self.amt_key else {}


def get_settings() -> Settings:
    """Build settings from the current environment."""
    return Settings()
