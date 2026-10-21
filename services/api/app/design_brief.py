"""Derived task wording; never a replacement for original user requirements."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


BriefText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class DesignEvidence(BaseModel):
    """A concise, auditable basis for an authored visual decision.

    This deliberately stores a source type and stable identifier rather than
    hidden model reasoning.  It is safe to show alongside a task plan.
    """
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    source: str = Field(pattern=r'^(user|reference|research|lesson|assumption)$')
    reference: str | None = Field(default=None, min_length=1, max_length=300)
    use: BriefText


class VisualDirection(BaseModel):
    """The design judgement that precedes a visual generation request."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    audience: BriefText
    theme: BriefText
    coreConcept: BriefText
    visualHierarchy: list[BriefText] = Field(min_length=1, max_length=5)
    formLanguage: list[BriefText] = Field(min_length=1, max_length=5)
    materialProcess: list[BriefText] = Field(min_length=1, max_length=5)
    colorRelationships: list[BriefText] = Field(min_length=1, max_length=4)
    compositionLighting: list[BriefText] = Field(min_length=1, max_length=4)
    avoid: list[BriefText] = Field(default_factory=list, max_length=8)
    evidence: list[DesignEvidence] = Field(default_factory=list, max_length=8)


class DesignBrief(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=3000)
    assumptions: list[BriefText] = Field(default_factory=list, max_length=12)
    openQuestions: list[BriefText] = Field(default_factory=list, max_length=8)
    # Optional to keep concise non-visual task briefs backward compatible.
    visualDirection: VisualDirection | None = None


def normalize_brief(value, task_id):
    return {**DesignBrief.model_validate(value).model_dump(exclude_none=True), 'sourceTaskId': task_id, 'status': 'derived'}
