"""Schemas for the state_history event stream (WBS 9.2)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TransitionField = Literal["design_status", "stage"]


class StateTransitionCreate(BaseModel):
    field: TransitionField
    to_value: str
    actor: str
    reason_code: str | None = None


class StateEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    field: str
    from_value: str | None
    to_value: str
    actor: str
    reason_code: str | None
    occurred_at: datetime


class OwnerChangeCreate(BaseModel):
    owner: str
    actor: str


class OwnerEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_owner: str | None
    to_owner: str
    actor: str
    occurred_at: datetime


class WinRateRead(BaseModel):
    won: int
    lost: int
    resolved: int
    rate: float | None
