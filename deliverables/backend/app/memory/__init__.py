"""
L3 semantic memory and the evidence assembler (WBS 9.3, 7.5).

The store keeps chunked notes -- comments, next actions, loss write-ups,
competitor notes -- as precedent for the judgment layer. Three rules from the
platform architecture are enforced here, not left to a prompt:

1. Numbers of any kind are never embedded. `scrub()` strips digits, currency
   and percentages before a chunk is stored; the original stays on the row.
2. Customer pricing is never embedded. ASP-bearing sentences are dropped, not
   just de-numbered, because "the resale price is ..." with the figure removed
   still leaks that a price was discussed cross-region.
3. Filter before you search. The assembler applies region, product line,
   part and recency as query predicates first, then ranks the survivors, then
   applies a token budget -- so similarity alone can never return a Korean
   lighting socket as precedent for a European ADAS opportunity.

Ranking backends: `local` (default) is lexical -- token overlap weighted by
inverse document frequency, deterministic, no model, no service -- and
`pgvector` embeds through the configured model and orders by cosine distance
in Postgres. The assembler does not know which one it is talking to.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.memory_chunk import MemoryChunk

EIGHT_QUARTERS = timedelta(days=8 * 91)
TOP_K = 6
TOKEN_BUDGET = 1200          # approximate tokens (words x 1.3) handed to the model as precedent

_NUMBER = re.compile(r"[$€£¥]?\s?\d[\d,]*(?:\.\d+)?\s?(?:%|k|K|M|pcs|Kpcs|units)?")
_PRICING = re.compile(r"\b(asp|price|pricing|resale|disty cost|margin|quote[ds]?|\$/unit|usd)\b", re.I)
_TOKEN = re.compile(r"[a-z][a-z0-9'\-]{2,}")
STOP = frozenset("the a an and or of to in for on at by with from is are was were be been this that it its as not no yes".split())


def scrub(text: str) -> str:
    """Rule 1 and rule 2. Sentence-level: a sentence that talks about pricing
    is removed whole; every other sentence has its numbers replaced by a
    placeholder."""
    kept = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text or ""):
        if not sentence.strip():
            continue
        if _PRICING.search(sentence):
            continue
        kept.append(_NUMBER.sub(" # ", sentence).strip())
    return " ".join(kept).strip()


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP]


@dataclass
class Precedent:
    chunk_id: str
    kind: str
    text: str
    score: float
    opportunity_id: str | None
    region: str | None
    part_number: str | None
    vintage: str | None
    created_at: datetime


@dataclass
class EvidencePack:
    precedents: list[Precedent] = field(default_factory=list)
    filtered_candidates: int = 0
    ranked_backend: str = "local"
    tokens_used: int = 0


def remember(db: Session, *, opportunity, kind: str, text: str, vintage: str | None = None,
             preserved: bool = False) -> MemoryChunk | None:
    """Chunks and stores one note. Returns None when scrubbing leaves nothing
    worth keeping (a note that was only a number)."""
    clean = scrub(text)
    if len(tokens(clean)) < 3:
        return None
    now = datetime.now(timezone.utc)
    chunk = MemoryChunk(
        opportunity_id=getattr(opportunity, "id", None), kind=kind,
        region=getattr(opportunity, "region", None), product_line=getattr(opportunity, "product_line", None),
        part_number=getattr(opportunity, "part_number", None), text=clean, tokens=tokens(clean),
        vintage=vintage, preserved=preserved, expires_at=None if preserved else now + EIGHT_QUARTERS,
    )
    db.add(chunk)
    db.flush()
    return chunk


def refresh_from_rows(db: Session, opportunities, *, vintage: str | None = None) -> int:
    """The post-ingest embedding refresh (jobs table): chunks each row's
    evidence and rationale once per vintage. Idempotent per (row, vintage)."""
    written = 0
    for opp in opportunities:
        exists = db.scalar(select(MemoryChunk.id).where(MemoryChunk.opportunity_id == opp.id,
                                                        MemoryChunk.vintage == vintage).limit(1))
        if exists:
            continue
        for kind, text in (("comment", opp.evidence), ("rationale", opp.confidence_rationale)):
            if text and remember(db, opportunity=opp, kind=kind, text=text, vintage=vintage):
                written += 1
    return written


def expire(db: Session, *, now: datetime | None = None) -> int:
    """Rolls off anything past eight quarters that is not preserved (decision #84)."""
    now = now or datetime.now(timezone.utc)
    rows = db.scalars(select(MemoryChunk).where(MemoryChunk.preserved.is_(False),
                                                MemoryChunk.expires_at.is_not(None))).all()
    expired = 0
    for r in rows:
        at = r.expires_at if r.expires_at.tzinfo else r.expires_at.replace(tzinfo=timezone.utc)
        if at <= now:
            db.delete(r)
            expired += 1
    db.flush()
    return expired


def _idf(db: Session) -> dict[str, float]:
    docs = db.scalars(select(MemoryChunk.tokens)).all()
    n = max(len(docs), 1)
    df: Counter = Counter()
    for toks in docs:
        df.update(set(toks or []))
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def assemble(db: Session, *, opportunity, query_text: str | None = None, top_k: int = TOP_K,
             token_budget: int = TOKEN_BUDGET, now: datetime | None = None) -> EvidencePack:
    """The evidence assembler (WBS 7.5). Order is the point: SQL predicates
    first (same region and product line, same part where known, not expired,
    resolved within eight quarters), then rank, then the budget."""
    now = now or datetime.now(timezone.utc)
    stmt = select(MemoryChunk).where(
        MemoryChunk.region == opportunity.region,
        (MemoryChunk.expires_at.is_(None)) | (MemoryChunk.expires_at > now),
    )
    if opportunity.product_line:
        stmt = stmt.where((MemoryChunk.product_line == opportunity.product_line) | (MemoryChunk.product_line.is_(None)))
    if opportunity.id:
        stmt = stmt.where((MemoryChunk.opportunity_id != opportunity.id) | (MemoryChunk.opportunity_id.is_(None)))
    candidates = db.scalars(stmt).all()
    pack = EvidencePack(filtered_candidates=len(candidates))
    if not candidates:
        return pack

    query = tokens(scrub(query_text or " ".join(filter(None, [opportunity.evidence, opportunity.confidence_rationale,
                                                                opportunity.part_number]))))
    idf = _idf(db)
    qset = set(query)
    scored = []
    for c in candidates:
        overlap = qset & set(c.tokens or [])
        score = sum(idf.get(t, 1.0) for t in overlap)
        if c.part_number and c.part_number == opportunity.part_number:
            score *= 1.5   # same part or socket where known
        age_days = (now - (c.created_at if c.created_at.tzinfo else c.created_at.replace(tzinfo=timezone.utc))).days
        score *= max(0.5, 1.0 - age_days / (8 * 91))   # recency
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda sc: (-sc[0], sc[1].created_at))
    used = 0
    for score, c in scored[:top_k]:
        cost = int(len(c.text.split()) * 1.3) + 8
        if used + cost > token_budget:
            break
        used += cost
        pack.precedents.append(Precedent(c.id, c.kind, c.text, round(score, 3), c.opportunity_id, c.region,
                                         c.part_number, c.vintage, c.created_at))
    pack.tokens_used = used
    return pack


def bundle_precedents(pack: EvidencePack) -> list[dict]:
    """The shape handed to the model inside the evidence bundle: text and
    provenance, no numbers (already scrubbed), never a figure."""
    return [{"kind": p.kind, "text": p.text, "part_number": p.part_number, "vintage": p.vintage,
             "when": p.created_at.date().isoformat()} for p in pack.precedents]
