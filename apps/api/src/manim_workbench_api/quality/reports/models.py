from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QualityRatingRecord:
    """An append-only human assessment kept separate from the frozen API contract."""

    id: UUID
    quality_report_id: UUID
    owner_id: UUID
    score: int
    notes: str | None
    created_at: datetime
