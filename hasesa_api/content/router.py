"""Course content for apps, with the same access rules as the website:

- module overviews and public concept units: anyone
- steps and other concept units: enrolled students and the guide ("full access")
- the guide's version of a module: guides only
- problem answers and explanations: never (graded on the server)
"""

import base64
import hashlib
import hmac
import json
import os
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel

from hasesa_api.access import access_level, has_full_access
from hasesa_api.config import get_settings
from hasesa_api.content.loader import (
    client_problems,
    concept_summary,
    get_content,
    mystery_of,
    summarize,
)
from hasesa_api.content.models import (
    ClientProblem,
    ConceptSummary,
    CurriculumRef,
    Discipline,
    Level,
    Material,
    ModuleSummary,
    SignoffItem,
    Status,
    StepKind,
    Video,
)
from hasesa_api.identity.deps import OptionalUserDep
from hasesa_api.models import User

router = APIRouter(tags=["content"])

# Content only changes with a deploy, and each Vercel deploy starts with an empty cache.
PUBLIC_CACHE = "public, max-age=300, s-maxage=86400"


# ---------- response shapes ----------


class StepPreview(BaseModel):
    """What the module page shows about a step before it is opened."""

    id: str
    title: str
    kind: StepKind
    minutes: int
    summary: str | None = None
    sections: list[str]
    units: list[str]


class ModuleDetail(ModuleSummary):
    body: str
    materials: list[Material]
    safety: list[str]
    signoff: list[SignoffItem]
    stepPreviews: list[StepPreview]


class StepOut(BaseModel):
    moduleId: str
    id: str
    index: int
    title: str
    kind: StepKind
    minutes: int
    units: list[str]
    video: Video | None = None
    summary: str | None = None
    sections: list[str]
    body: str


class ConceptOut(BaseModel):
    id: str
    title: str
    summary: str
    status: Status
    public: bool
    curriculum: list[CurriculumRef]
    body: str
    problems: list[ClientProblem]


class GuideOut(BaseModel):
    moduleId: str
    guide: str


class SearchModule(BaseModel):
    id: str
    title: str
    tagline: str
    mystery: str
    disciplines: list[Discipline]
    level: Level
    hours: float


class SearchUnit(BaseModel):
    id: str
    title: str
    summary: str


class SearchIndex(BaseModel):
    """The header search's index. Lists fields explicitly so nothing private slips in."""

    modules: list[SearchModule]
    units: list[SearchUnit]


class ContentVersion(BaseModel):
    commit: str | None
    content: str


# ---------- access ----------


def _require_full(user: User | None) -> None:
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.", headers={"WWW-Authenticate": "Bearer"})
    if not has_full_access(access_level(user.role, user.paid_until)):
        raise HTTPException(status_code=403, detail="Enrol at the Academy to unlock this.")


def confidential_client(authorization: Annotated[str | None, Header()] = None) -> str:
    """HTTP Basic auth with a confidential client's ID and secret (the website's server).

    Checked against CLIENT_SECRETS only, so the content endpoints never need the database.
    """
    scheme, _, encoded = (authorization or "").partition(" ")
    try:
        client_id, sep, secret = base64.b64decode(encoded, validate=True).decode().partition(":")
    except ValueError:
        client_id, sep, secret = "", "", ""
    if scheme.lower() != "basic" or not sep:
        raise HTTPException(status_code=401, detail="Client authentication required.")
    expected = get_settings().client_secrets.get(client_id)
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Client authentication failed.")
    return client_id


# ---------- the full bundle ----------


@lru_cache
def _bundle() -> tuple[bytes, str]:
    c = get_content()
    data: dict[str, Any] = {
        "modules": [m.model_dump(exclude_none=True) for m in c.modules],
        "concepts": [x.model_dump(exclude_none=True) for x in c.concepts.values()],
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return raw, hashlib.sha256(raw).hexdigest()[:16]


@router.get("/content/bundle", responses={200: {"description": "All content, answers included."}})
async def bundle(client_id: Annotated[str, Depends(confidential_client)]) -> Response:
    """Everything, including answers and guide notes, for a trusted server (the website's build)."""
    raw, version = _bundle()
    return Response(raw, media_type="application/json", headers={"ETag": f'"{version}"', "Cache-Control": "no-store"})


@router.get("/content/version")
async def version(response: Response) -> ContentVersion:
    """The deployed commit and a hash of the content, to know when new content is live."""
    response.headers["Cache-Control"] = "no-store"
    return ContentVersion(commit=os.environ.get("VERCEL_GIT_COMMIT_SHA"), content=_bundle()[1])


# ---------- modules ----------


def _module_or_404(module_id: str):
    m = get_content().module(module_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Module not found.")
    return m


@router.get("/modules", response_model_exclude_none=True)
async def list_modules(response: Response) -> list[ModuleSummary]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    c = get_content()
    return [summarize(m, c) for m in c.modules]


@router.get("/modules/{module_id}", response_model_exclude_none=True)
async def get_module(module_id: str, response: Response) -> ModuleDetail:
    m = _module_or_404(module_id)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return ModuleDetail(
        **summarize(m, get_content()).model_dump(),
        body=m.body,
        materials=m.materials,
        safety=m.safety,
        signoff=m.signoff,
        stepPreviews=[
            StepPreview(
                id=s.id,
                title=s.title,
                kind=s.kind,
                minutes=s.minutes,
                summary=s.summary,
                sections=s.sections,
                units=s.units,
            )
            for s in m.steps
        ],
    )


@router.get("/modules/{module_id}/steps/{step_id}", response_model_exclude_none=True)
async def get_step(module_id: str, step_id: str, user: OptionalUserDep, response: Response) -> StepOut:
    m = _module_or_404(module_id)
    index = next((i for i, s in enumerate(m.steps) if s.id == step_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Step not found.")
    _require_full(user)
    response.headers["Cache-Control"] = "private, no-store"
    s = m.steps[index]
    return StepOut(moduleId=m.id, index=index, **s.model_dump())


@router.get("/modules/{module_id}/guide")
async def get_guide(module_id: str, user: OptionalUserDep, response: Response) -> GuideOut:
    m = _module_or_404(module_id)
    if user is None or user.role != "guide":
        raise HTTPException(status_code=403, detail="Only guides can see the guide's version.")
    response.headers["Cache-Control"] = "private, no-store"
    return GuideOut(moduleId=m.id, guide=m.guide)


# ---------- concepts ----------


@router.get("/concepts")
async def list_concepts(response: Response) -> list[ConceptSummary]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return [concept_summary(c) for c in get_content().concepts.values()]


@router.get("/concepts/{concept_id}", response_model_exclude_none=True)
async def get_concept(concept_id: str, user: OptionalUserDep, response: Response) -> ConceptOut:
    c = get_content().concepts.get(concept_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Concept not found.")
    if c.public:
        response.headers["Cache-Control"] = PUBLIC_CACHE
    else:
        _require_full(user)
        response.headers["Cache-Control"] = "private, no-store"
    return ConceptOut(
        id=c.id,
        title=c.title,
        summary=c.summary,
        status=c.status,
        public=c.public,
        curriculum=c.curriculum,
        body=c.body,
        problems=client_problems(c),
    )


# ---------- search ----------


@router.get("/search-index")
async def search_index(response: Response) -> SearchIndex:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    c = get_content()
    return SearchIndex(
        modules=[
            SearchModule(
                id=m.id,
                title=m.title,
                tagline=m.tagline,
                mystery=mystery_of(m.hook, m.tagline),
                disciplines=m.disciplines,
                level=m.level,
                hours=m.hours,
            )
            for m in c.modules
        ],
        units=[SearchUnit(id=x.id, title=x.title, summary=x.summary) for x in c.concepts.values()],
    )
