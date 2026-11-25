"""Reads and validates everything under content/.

A port of hasesa-lab-web lib/content/load.ts and sections.ts: the same files,
rules and error messages, so a bad file fails the same way it always has.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from hasesa_api.content.models import (
    LEVELS,
    ClientMcq,
    ClientNumeric,
    ClientProblem,
    Concept,
    ConceptFront,
    ConceptSummary,
    CurriculumRef,
    Module,
    ModuleFront,
    ModuleSummary,
    SampleRef,
    Step,
    StepFront,
    StepOutline,
)

CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)


class ContentError(Exception):
    """A content file is invalid. The message names the file and field."""


@dataclass(frozen=True)
class Content:
    modules: list[Module]
    concepts: dict[str, Concept]  # in file-name order

    def module(self, module_id: str) -> Module | None:
        return next((m for m in self.modules if m.id == module_id), None)


# ---------- files ----------


def _yaml() -> YAML:
    # YAML 1.2, like js-yaml in the web app ("yes" stays a string, 1.5e3 is a number).
    y = YAML(typ="safe", pure=True)
    y.version = (1, 2)
    return y


def _read(file: Path, root: Path) -> tuple[dict, str]:
    text = file.read_text(encoding="utf-8")
    m = _FRONT.match(text)
    if not m:
        return {}, text
    data = _yaml().load(m.group(1)) or {}
    if not isinstance(data, dict):
        raise ContentError(f"Invalid content in {file.relative_to(root.parent)}:\n  (root): Expected object")
    return data, m.group(2)


def _parse[M: BaseModel](model: type[M], data: dict, file: Path, root: Path) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        issues = "\n".join(f"  {'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}" for err in e.errors())
        raise ContentError(f"Invalid content in {file.relative_to(root.parent)}:\n{issues}") from e


def _md_files(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(f.name for f in directory.iterdir() if f.is_file() and f.name.endswith(".md"))


# ---------- sections (port of sections.ts) ----------

_HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _kind_of(title: str) -> str:
    t = title.lower()
    if re.search(r"safety", t):
        return "safety"
    if re.search(r"theory", t):
        return "theory"
    if re.search(r"^(do|build|try|make|record)\b|do it better", t):
        return "do"
    if re.search(r"^(notice|predict|think|look|the question)", t):
        return "notice"
    return "other"


def _slug(s: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s.lower())) or "section"


def _js_trim(s: str) -> str:
    # JavaScript's String.trim() also strips the byte-order mark.
    return s.strip().strip("﻿").strip()


def split_sections(md: str, intro_title: str = "Start") -> list[dict]:
    """Split Markdown into its "## " sections. Text before the first heading becomes
    a section titled `intro_title`. Headings inside fenced code blocks are ignored."""
    out: list[dict] = [{"title": intro_title, "lines": []}]
    fenced = False
    for line in md.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        h = None if fenced else _HEADING.match(line)
        if h:
            out.append({"title": h.group(1), "lines": []})
        else:
            out[-1]["lines"].append(line)
    used: set[str] = set()
    sections = []
    for s in out:
        body = _js_trim("\n".join(s["lines"]))
        if not body:
            continue
        base = _slug(s["title"])
        sid, n = base, 2
        while sid in used:
            sid, n = f"{base}-{n}", n + 1
        used.add(sid)
        short = s["title"].split(":")[0].strip()
        label = f"{short[:22]}…" if len(short) > 24 else short
        sections.append({"id": sid, "title": s["title"], "label": label, "kind": _kind_of(s["title"]), "body": body})
    return sections


# ---------- loading ----------


def _load_concepts(directory: Path, root: Path) -> dict[str, Concept]:
    out: dict[str, Concept] = {}
    for name in _md_files(directory):
        cid = name.removesuffix(".md")
        file = directory / name
        if not SLUG.match(cid):
            raise ContentError(f"Concept file name must be a lowercase slug: {name}")
        data, body = _read(file, root)
        fm = _parse(ConceptFront, data, file, root)
        seen: set[str] = set()
        for p in fm.problems:
            if p.id in seen:
                raise ContentError(f'Duplicate problem id "{p.id}" in {name}')
            seen.add(p.id)
        out[cid] = Concept(id=cid, body=_js_trim(body), **fm.model_dump())
    return out


_STEP_FILE = re.compile(r"^\d+-(.+)\.md$")


def _load_module(directory: Path, mid: str, concepts: dict[str, Concept], root: Path) -> Module:
    file = directory / "module.md"
    data, body = _read(file, root)
    fm = _parse(ModuleFront, data, file, root)

    steps: list[Step] = []
    steps_dir = directory / "steps"
    for name in _md_files(steps_dir):
        # "03-antenna.md" -> step id "antenna"; the number only orders the steps.
        m = _STEP_FILE.match(name)
        if not m or not SLUG.match(m.group(1)):
            raise ContentError(f"Step file must be named NN-slug.md: {mid}/steps/{name}")
        # "guide" is the URL of the guide's version, so no step can use it.
        if m.group(1) == "guide":
            raise ContentError(f'Step id "guide" is reserved: {mid}/steps/{name}')
        step_file = steps_dir / name
        sdata, sbody = _read(step_file, root)
        sfm = _parse(StepFront, sdata, step_file, root)
        for u in sfm.units:
            if u not in concepts:
                raise ContentError(f'Step {mid}/{m.group(1)} uses unknown concept "{u}"')
        text = _js_trim(sbody)
        # The step's section names: a preview that gives nothing away ("Watch · Predict · Test").
        sections = [s["label"] for s in split_sections(text, "") if s["title"]]
        steps.append(Step(id=m.group(1), sections=sections, body=text, **sfm.model_dump()))
    if not steps:
        raise ContentError(f"Module {mid} has no steps")
    if len({s.id for s in steps}) != len(steps):
        raise ContentError(f"Module {mid} has duplicate step ids")
    if fm.publicSample not in concepts:
        raise ContentError(f'Module {mid} publicSample "{fm.publicSample}" is not a concept')

    guide_file = directory / "guide.md"
    guide = _js_trim(_read(guide_file, root)[1]) if guide_file.exists() else ""
    if not guide:
        raise ContentError(f"Module {mid} is missing guide.md")

    return Module(id=mid, body=_js_trim(body), steps=steps, guide=guide, **fm.model_dump())


def load_content(root: Path = CONTENT_DIR) -> Content:
    concepts = _load_concepts(root / "concepts", root)
    modules_dir = root / "modules"
    ids = sorted(d.name for d in modules_dir.iterdir() if d.is_dir()) if modules_dir.is_dir() else []
    modules = []
    for mid in ids:
        if not SLUG.match(mid):
            raise ContentError(f"Module folder must be a lowercase slug: {mid}")
        modules.append(_load_module(modules_dir / mid, mid, concepts, root))
    # Easiest first, then by id.
    modules.sort(key=lambda m: (LEVELS.index(m.level), m.id))
    # A public sample concept must actually be open to the public.
    for m in modules:
        if not concepts[m.publicSample].public:
            raise ContentError(f'Module {m.id}: publicSample "{m.publicSample}" must have public: true')
    return Content(modules=modules, concepts=concepts)


@lru_cache
def get_content() -> Content:
    """The content, loaded and validated once per process."""
    return load_content()


# ---------- derived views ----------


def module_units(m: Module) -> list[str]:
    """Every concept unit a module uses, in the order its steps first need them."""
    out: list[str] = []
    for s in m.steps:
        for u in s.units:
            if u not in out:
                out.append(u)
    return out


def module_curriculum(m: Module, concepts: dict[str, Concept]) -> list[CurriculumRef]:
    """Curriculum topics a module covers, de-duplicated across its concept units."""
    seen: dict[str, CurriculumRef] = {}
    for s in m.steps:
        for u in s.units:
            c = concepts.get(u)
            for ref in c.curriculum if c else []:
                seen[f"{ref.subject}|{ref.grade}|{ref.unit}"] = ref
    return sorted(seen.values(), key=lambda r: (r.grade, r.subject))


def summarize(m: Module, content: Content) -> ModuleSummary:
    sample = content.concepts[m.publicSample]
    return ModuleSummary(
        id=m.id,
        title=m.title,
        tagline=m.tagline,
        disciplines=m.disciplines,
        level=m.level,
        hook=m.hook,
        goal=m.goal,
        whatYouBuild=m.whatYouBuild,
        hours=m.hours,
        status=m.status,
        trailer=m.trailer,
        stepCount=len(m.steps),
        steps=[StepOutline(id=s.id, title=s.title, kind=s.kind, minutes=s.minutes) for s in m.steps],
        curriculum=module_curriculum(m, content.concepts),
        publicSample=SampleRef(id=sample.id, title=sample.title),
        featured=m.featured,
    )


def concept_summary(c: Concept) -> ConceptSummary:
    return ConceptSummary(id=c.id, title=c.title, summary=c.summary, problemCount=len(c.problems))


def client_problems(c: Concept) -> list[ClientProblem]:
    """Problems with answers and explanations removed, for apps."""
    return [
        ClientMcq(id=p.id, q=p.q, choices=p.choices) if p.type == "mcq" else ClientNumeric(id=p.id, q=p.q, unit=p.unit)
        for p in c.problems
    ]


_MYSTERY = re.compile(r"[^.!?…—]*\?\s*$")


def mystery_of(hook: str, tagline: str) -> str:
    """The last sentence of a hook is the mystery itself (port of catalogue.ts mysteryOf)."""
    m = _MYSTERY.search(hook)
    return (m.group(0).strip() if m else "") or tagline
