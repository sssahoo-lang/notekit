"""Compare retrieval configurations on the same fixed syllabus.

`config.SWEEP` has listed four configurations since milestone 2 with a comment
promising a faithfulness figure for each, and nothing ever ran them. This runs
them.

Only the retrieval half varies for free. A configuration that changes chunking
needs its own index, because chunk size is decided at ingestion. Those are
reported as needing a build rather than silently compared against an index built
with different settings, which would attribute the difference to the wrong
thing.
"""

from __future__ import annotations

from pydantic import BaseModel

from . import config, db, evaluation
from .models import Syllabus
from .pipeline import run_course


class ConfigResult(BaseModel):
    name: str
    runs: list[float] = []
    claims: int = 0
    supported: int = 0
    cost_usd: float = 0.0
    skipped: str | None = None

    @property
    def faithfulness(self) -> float | None:
        return self.supported / self.claims if self.claims else None

    @property
    def spread(self) -> float | None:
        return max(self.runs) - min(self.runs) if len(self.runs) > 1 else None


def needs_own_index(cfg: config.RetrievalConfig) -> bool:
    """True when the configuration changes how documents were chunked."""
    base = config.EMBEDDING
    return (
        cfg.chunk_tokens != base.chunk_tokens
        or cfg.chunk_overlap != base.chunk_overlap
        or cfg.embedding_model != base.embedding_model
    )


def namespace_for(cfg: config.RetrievalConfig, base_namespace: str) -> str:
    """Where a chunking-variant configuration's index would live."""
    return base_namespace if not needs_own_index(cfg) else f"{base_namespace}--{cfg.name}"


def run_sweep(
    syllabus: Syllabus,
    *,
    namespace: str,
    repeat: int = 1,
    configs: list[config.RetrievalConfig] | None = None,
    on_progress=None,
) -> list[ConfigResult]:
    """Score each configuration against the same syllabus and corpus."""
    from . import llm

    results: list[ConfigResult] = []

    for cfg in configs or config.SWEEP:
        result = ConfigResult(name=cfg.name)
        target = namespace_for(cfg, namespace)

        if needs_own_index(cfg):
            with db.connect() as conn:
                populated = db.namespace_stats(conn, target)["chunks"] > 0
            if not populated:
                result.skipped = (
                    f"needs its own index (chunk {cfg.chunk_tokens}/"
                    f"{cfg.chunk_overlap}); build it into '{target}' first"
                )
                results.append(result)
                if on_progress:
                    on_progress(result)
                continue

        for _ in range(repeat):
            llm.reset_usage()
            _, notes = run_course(
                "",
                syllabus=syllabus,
                skip_ingest=True,
                namespace=target,
                cfg=cfg,
            )
            scored = evaluation.evaluate_course(notes, syllabus.modules)
            summary = evaluation.aggregate(scored)

            result.claims += summary["claims"]
            result.supported += summary["supported"]
            if summary["faithfulness"] is not None:
                result.runs.append(summary["faithfulness"])
            result.cost_usd += llm.usage_report()[1]

        results.append(result)
        if on_progress:
            on_progress(result)

    return results
