"""Pydantic request/response models. Length caps here are the input limits from the spec."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class ChatResponse(BaseModel):
    outcome: Literal["answered", "stale_warning", "no_connection", "unknown"]
    answer: str
    paths: list[list[str]]
    steps: list[list[dict[str, Any]]]
    rows: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    highlight: list[str]
    trace: list[dict[str, Any]]
    check: str
    choices: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    mode: Literal["online", "offline"]


class ReviewRequest(BaseModel):
    old_id: str = Field(min_length=1, max_length=20)
    by: str = Field(min_length=1, max_length=80)


class GraphRequest(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=200)


class ProposeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    author: str | None = Field(default=None, max_length=80)


class ConfirmRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    system: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=3, max_length=120)
    old: str = Field(min_length=1, max_length=20)
    author: str = Field(min_length=1, max_length=80)
