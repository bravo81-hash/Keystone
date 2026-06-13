"""Optional read-only ingest of external index-book positions (Stage 8, off by default).

When ``risk.index_book_ingest.enabled`` is true, this would read the other app's
(index book) positions so Keystone can avoid doubling correlated risk. The source
is a documented stub here; disabled config returns no positions.
"""

from __future__ import annotations

import logging

from config.schema import IndexBookIngestCfg
from portfolio.budgets import BookItem

logger = logging.getLogger(__name__)


def ingest_index_book(cfg: IndexBookIngestCfg) -> list[BookItem]:
    """Return external index-book positions as BookItems (empty unless enabled)."""

    if not cfg.enabled:
        return []
    # Integration seam: read read-only positions from cfg.source (e.g. the index
    # app's store or an IBKR account snapshot). Not wired in v1.
    logger.warning(
        "index_book_ingest enabled but source %r not wired; returning no positions",
        cfg.source,
    )
    return []
