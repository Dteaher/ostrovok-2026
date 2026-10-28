"""Typed, bounded domain state; models never own prices or inventory."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PreferenceField = Literal[
    "breakfast", "pool", "refundable", "quiet", "direct_only", "max_beach_m", "min_rating", "stars"
]
PreferenceMode = Literal["required", "preferred"]


class TripRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    destination: str | None = Field(default=None, max_length=100)
    origin: str = Field(default="Москва", max_length=100)
    check_in: date | None = None
    nights: int = Field(default=7, ge=1, le=30)
    adults: int = Field(default=2, ge=1, le=8)
    children_ages: list[int] = Field(default_factory=list, max_length=6)
    budget: int | None = Field(default=None, ge=1000, le=10_000_000)
    transport: Literal["flight", "train", "self"] = "flight"
    direct_only: bool = False
    breakfast: bool = False
    refundable: bool = False
    pets: bool = False
    pool: bool = False
    quiet: bool = False
    accessible: bool = False
    max_beach_m: int | None = Field(default=None, ge=0, le=10000)
    min_rating: float = Field(default=0, ge=0, le=10)
    stars: int = Field(default=0, ge=0, le=5)
    preference_modes: dict[PreferenceField, PreferenceMode] = Field(default_factory=dict)
    budget_scope: Literal["trip", "hotel"] = "trip"
    assumptions: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)

    @field_validator("children_ages")
    @classmethod
    def validate_children(cls, ages: list[int]) -> list[int]:
        if any(age < 0 or age > 17 for age in ages):
            raise ValueError("Возраст ребёнка должен быть от 0 до 17 лет")
        return ages


def is_required(req: TripRequirements, field: str) -> bool:
    """Absent modes preserve older sessions; quiet was historically a preference."""
    value = getattr(req, field)
    active = value is not None if field == "max_beach_m" else bool(value)
    return (
        active
        and req.preference_modes.get(field, "preferred" if field == "quiet" else "required")
        == "required"
    )


def search_terms(req: TripRequirements) -> dict:
    """Canonical search meaning, independent of provenance or redundant modes."""
    terms = req.model_dump(mode="json", exclude={"assumptions", "preference_modes"})
    modes = {}
    for field, mode in req.preference_modes.items():
        value = getattr(req, field)
        active = value is not None if field == "max_beach_m" else bool(value)
        default = "preferred" if field == "quiet" else "required"
        if active and mode != default:
            modes[field] = mode
    if modes:
        terms["preference_modes"] = modes
    return terms


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def trim_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Напишите пожелания к поездке")
        return value


class UpdateMessageRequest(MessageRequest):
    revision: int = Field(ge=1)


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class SelectRequest(RevisionRequest):
    plan_id: str = Field(min_length=1, max_length=100)


class PatchRequest(RevisionRequest):
    patch: dict


class CheckoutRequest(RevisionRequest):
    accept_demo: Literal[True]
    traveler_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("traveler_name", "email")
    @classmethod
    def strip_fields(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Поле не должно быть пустым")
        return value

    @field_validator("email")
    @classmethod
    def email_shape(cls, value: str | None) -> str | None:
        import re

        if value is None:
            return None
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Укажите корректный email")
        return value
