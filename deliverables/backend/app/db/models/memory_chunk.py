"""
memory_chunk: L3 semantic memory (WBS 9.3) -- comments, next actions, loss
write-ups and competitor notes, chunked per the Step 5 table, retrieved as
precedent and never as fact.

Two rules are enforced at write time, not at read time: numbers of any kind
are never embedded (a figure recovered from a search is a figure nobody can
audit), and customer pricing is never embedded (retrieval crosses region
boundaries by design; pricing must not). The chunk text stored here has
already been scrubbed; the original stays on the row it came from.

`embedding` holds a vector when an embedding backend is configured (pgvector
in production); the local backend ranks lexically and leaves it null. Rows
expire after eight quarters (decision #84) unless `preserved` is set.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryChunk(Base):
    __tablename__ = "memory_chunk"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunity.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)      # comment | next_action | loss_writeup | competitor_note
    region: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    product_line: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    text: Mapped[str] = mapped_column(String, nullable=False)          # scrubbed: no numbers, no pricing
    tokens: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # lexical index for the local backend
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vintage: Mapped[str | None] = mapped_column(String(36), nullable=True)   # snapshot or run id the note came from
    preserved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
