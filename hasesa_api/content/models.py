"""Content shapes. Field names are camelCase on purpose: they match the web app's
TypeScript types (hasesa-lab-web lib/content/types.ts) exactly, so the JSON this
API serves drops straight into the existing pages.

The front-matter models mirror the zod schemas in hasesa-lab-web
lib/content/load.ts: same fields, defaults and limits.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["ai-draft", "expert-reviewed", "classroom-tested"]
Level = Literal["beginner", "intermediate", "advanced"]
Discipline = Literal["physics", "chemistry", "biology", "mathematics", "technology"]
StepKind = Literal["hook", "investigate", "build", "finish"]
LEVELS: tuple[Level, ...] = ("beginner", "intermediate", "advanced")

NonEmpty = Annotated[str, Field(min_length=1)]


class _Model(BaseModel):
    # Unknown front-matter keys are ignored, like zod's default.
    model_config = ConfigDict(extra="ignore")


class Video(_Model):
    youtubeId: str | None = None
    src: str | None = None
    credit: str | None = None


class CurriculumRef(_Model):
    subject: Discipline
    grade: Annotated[int, Field(ge=7, le=12)]
    unit: NonEmpty
    code: str | None = None


class McqProblem(_Model):
    id: NonEmpty
    type: Literal["mcq"]
    q: NonEmpty
    choices: Annotated[list[NonEmpty], Field(min_length=2, max_length=6)]
    answerIndex: Annotated[int, Field(ge=0)]
    explanation: NonEmpty

    @model_validator(mode="after")
    def answer_in_range(self) -> "McqProblem":
        if self.answerIndex >= len(self.choices):
            raise ValueError("answerIndex is past the last choice")
        return self


class NumericProblem(_Model):
    id: NonEmpty
    type: Literal["numeric"]
    q: NonEmpty
    answer: float
    tolerancePct: Annotated[float, Field(ge=0, le=50)] = 2
    unit: str | None = None
    explanation: NonEmpty


Problem = Annotated[McqProblem | NumericProblem, Field(discriminator="type")]


class ConceptFront(_Model):
    title: NonEmpty
    summary: NonEmpty
    status: Status
    public: bool = False
    curriculum: list[CurriculumRef] = []
    problems: Annotated[list[Problem], Field(min_length=1)]


class StepFront(_Model):
    title: NonEmpty
    kind: StepKind
    minutes: Annotated[int, Field(ge=5, le=300)]
    units: list[str] = []
    video: Video | None = None
    summary: Annotated[str, Field(min_length=1, max_length=240)] | None = None


class Material(_Model):
    item: NonEmpty
    note: str | None = None


class SignoffItem(_Model):
    id: NonEmpty
    text: NonEmpty


class ModuleFront(_Model):
    title: NonEmpty
    tagline: NonEmpty
    disciplines: Annotated[list[Discipline], Field(min_length=1)]
    level: Level
    hook: NonEmpty
    goal: NonEmpty
    whatYouBuild: NonEmpty
    hours: Annotated[float, Field(ge=1, le=40)]
    trailer: Video | None = None
    status: Status
    materials: Annotated[list[Material], Field(min_length=1)]
    safety: Annotated[list[NonEmpty], Field(min_length=1)]
    signoff: Annotated[list[SignoffItem], Field(min_length=1)]
    publicSample: NonEmpty
    featured: bool = False


# ---------- loaded content ----------


class Concept(ConceptFront):
    id: str
    body: str


class Step(StepFront):
    id: str
    # The names of the step's "## " sections, in order.
    sections: list[str]
    body: str


class Module(ModuleFront):
    id: str
    body: str
    steps: list[Step]
    # The guide's version (guide.md). Only ever sent to guides.
    guide: str


# ---------- public shapes ----------


class ClientMcq(BaseModel):
    id: str
    type: Literal["mcq"] = "mcq"
    q: str
    choices: list[str]


class ClientNumeric(BaseModel):
    id: str
    type: Literal["numeric"] = "numeric"
    q: str
    unit: str | None = None


ClientProblem = ClientMcq | ClientNumeric


class StepOutline(BaseModel):
    id: str
    title: str
    kind: StepKind
    minutes: int


class SampleRef(BaseModel):
    id: str
    title: str


class ModuleSummary(BaseModel):
    """What a module card or preview needs. Safe for anyone."""

    id: str
    title: str
    tagline: str
    disciplines: list[Discipline]
    level: Level
    hook: str
    goal: str
    whatYouBuild: str
    hours: float
    status: Status
    trailer: Video | None = None
    stepCount: int
    steps: list[StepOutline]
    curriculum: list[CurriculumRef]
    publicSample: SampleRef
    featured: bool


class ConceptSummary(BaseModel):
    id: str
    title: str
    summary: str
    problemCount: int
