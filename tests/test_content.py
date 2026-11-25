"""Content: the real content/ folder must load, follow the course rules, and never
leak answers. Ported from the web app's content, sections, catalogue and
search-index tests. None of these need a database."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from hasesa_api import config
from hasesa_api.content.loader import (
    ContentError,
    get_content,
    load_content,
    module_units,
    mystery_of,
    split_sections,
)

content = get_content()
pytestmark = pytest.mark.anyio


# ---------- the real content ----------


def test_has_modules() -> None:
    assert content.modules


@pytest.mark.parametrize("m", content.modules, ids=lambda m: m.id)
def test_module_rules(m) -> None:
    minutes = sum(s.minutes for s in m.steps)
    assert m.hours * 60 * 0.75 <= minutes <= m.hours * 60 * 1.25, "steps must add up to the module's hours"
    for s in m.steps:
        assert s.sections, f"{s.id} has no named sections"
        assert len(split_sections(s.body)) >= 2, f"{m.id}/{s.id}"
    assert m.steps[0].kind == "hook"
    assert m.steps[-1].kind == "finish"
    units = module_units(m)
    assert units and all(u in content.concepts for u in units)
    assert len({s.id for s in m.signoff}) == len(m.signoff)
    assert mystery_of(m.hook, m.tagline).endswith("?")


def test_every_concept_is_used_by_some_module() -> None:
    used = {u for m in content.modules for u in module_units(m)}
    assert [c for c in content.concepts if c not in used] == []


def test_every_concept_has_at_least_3_problems() -> None:
    for c in content.concepts.values():
        assert len(c.problems) >= 3, c.id


def test_modules_are_listed_easiest_first() -> None:
    order = ["beginner", "intermediate", "advanced"]
    ranks = [order.index(m.level) for m in content.modules]
    assert ranks == sorted(ranks)


# ---------- sections ----------


def test_split_sections_labels_and_kinds() -> None:
    s = split_sections(
        "Intro text\n\n## Safety first\nCareful.\n\n## Do: string up the antenna\n1. One\n\n"
        "## Notice\nHmm\n\n## Theory: just enough\nMaths"
    )
    assert [(x["label"], x["kind"]) for x in s] == [
        ("Start", "other"),
        ("Safety first", "safety"),
        ("Do", "do"),
        ("Notice", "notice"),
        ("Theory", "theory"),
    ]
    assert s[2]["title"] == "Do: string up the antenna"
    assert s[2]["body"] == "1. One"


def test_split_sections_ignores_code_blocks_and_drops_empty_sections() -> None:
    s = split_sections("## Code\n```\n## not a heading\n```\n## Empty\n\n## Last\nx")
    assert [x["title"] for x in s] == ["Code", "Last"]


def test_split_sections_unique_ids() -> None:
    assert [x["id"] for x in split_sections("## Do\na\n## Do\nb")] == ["do", "do-2"]


def test_long_labels_are_shortened() -> None:
    [s] = split_sections("## A very long section title indeed here\nx")
    assert s["label"] == "A very long section ti…"


# ---------- validation errors name the file ----------


def _write(root: Path, rel: str, text: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


CONCEPT = """---
title: T
summary: S
status: ai-draft
public: true
problems:
  - {id: a, type: mcq, q: "?", choices: ["x", "y"], answerIndex: 1, explanation: "e"}
  - {id: b, type: numeric, q: "?", answer: 1.5e3, explanation: "e"}
---
Body
"""

MODULE = """---
title: M
tagline: T
disciplines: [physics]
level: beginner
hook: "Why?"
goal: G
whatYouBuild: W
hours: 1
status: ai-draft
materials: [{item: I}]
safety: [S]
signoff: [{id: s, text: T}]
publicSample: unit
---
Intro
"""

STEP = """---
title: Step
kind: hook
minutes: 60
units: [unit]
---
## Watch
x
"""


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    _write(root, "concepts/unit.md", CONCEPT)
    _write(root, "modules/demo/module.md", MODULE)
    _write(root, "modules/demo/steps/01-start.md", STEP)
    _write(root, "modules/demo/guide.md", "Guide notes")
    return root


def test_small_tree_loads(tmp_path: Path) -> None:
    c = load_content(_tree(tmp_path))
    [m] = c.modules
    assert m.steps[0].id == "start" and m.steps[0].sections == ["Watch"]
    a, b = c.concepts["unit"].problems
    assert b.answer == 1500 and b.tolerancePct == 2  # YAML number and default tolerance


@pytest.mark.parametrize(
    ("rel", "text", "message"),
    [
        ("modules/demo/steps/01-start.md", STEP.replace("minutes: 60", "minutes: 2"), "steps/01-start.md:\n  minutes"),
        ("modules/demo/steps/02-guide.md", STEP, 'Step id "guide" is reserved'),
        ("modules/demo/steps/2.md", STEP, "Step file must be named NN-slug.md"),
        ("modules/demo/steps/01-start.md", STEP.replace("[unit]", "[nope]"), 'uses unknown concept "nope"'),
        ("modules/demo/guide.md", "", "Module demo is missing guide.md"),
        ("concepts/unit.md", CONCEPT.replace("public: true", "public: false"), "must have public: true"),
        ("concepts/unit.md", CONCEPT.replace("id: b", "id: a"), 'Duplicate problem id "a"'),
        ("concepts/unit.md", CONCEPT.replace("answerIndex: 1", "answerIndex: 2"), "answerIndex is past"),
        ("concepts/Bad_Name.md", CONCEPT, "Concept file name must be a lowercase slug"),
        ("modules/demo/module.md", MODULE.replace("level: beginner", "level: easy"), "module.md:\n  level"),
    ],
)
def test_invalid_content_is_refused(tmp_path: Path, rel: str, text: str, message: str) -> None:
    root = _tree(tmp_path)
    _write(root, rel, text)
    with pytest.raises(ContentError) as e:
        load_content(root)
    assert message in str(e.value)


# ---------- endpoints ----------

WEB_SECRET = "content-test-secret"


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLIENT_SECRETS", f"hasesa-web:{WEB_SECRET}")
    config.get_settings.cache_clear()
    from hasesa_api.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    config.get_settings.cache_clear()


def _no_answers(data) -> None:
    text = json.dumps(data)
    for key in ('"answer":', '"answerIndex":', '"explanation":', '"tolerancePct":', '"guide":'):
        assert key not in text, f"{key} leaked"


async def test_module_list_is_public_and_cacheable(client) -> None:
    r = await client.get("/v1/modules")
    assert r.status_code == 200
    assert [m["id"] for m in r.json()] == [m.id for m in content.modules]
    assert "s-maxage" in r.headers["cache-control"]
    _no_answers(r.json())


async def test_module_page_shows_previews_but_not_step_bodies(client) -> None:
    m = content.modules[0]
    r = await client.get(f"/v1/modules/{m.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["publicSample"]["id"] == m.publicSample
    assert [s["id"] for s in data["stepPreviews"]] == [s.id for s in m.steps]
    assert all("body" not in s for s in data["stepPreviews"])
    _no_answers(data)
    assert (await client.get("/v1/modules/nope")).status_code == 404


async def test_public_concept_is_open_without_answers(client) -> None:
    c = next(x for x in content.concepts.values() if x.public)
    r = await client.get(f"/v1/concepts/{c.id}")
    assert r.status_code == 200
    assert len(r.json()["problems"]) == len(c.problems)
    _no_answers(r.json())


async def test_locked_content_needs_sign_in(client) -> None:
    locked = next(x for x in content.concepts.values() if not x.public)
    m = content.modules[0]
    assert (await client.get(f"/v1/concepts/{locked.id}")).status_code == 401
    assert (await client.get(f"/v1/modules/{m.id}/steps/{m.steps[0].id}")).status_code == 401
    assert (await client.get(f"/v1/modules/{m.id}/guide")).status_code == 403
    assert (await client.get(f"/v1/modules/{m.id}/steps/nope")).status_code == 404
    bad = {"Authorization": "Bearer not-a-token"}
    assert (await client.get(f"/v1/concepts/{locked.id}", headers=bad)).status_code == 401


async def test_search_index_lists_everything_and_nothing_private(client) -> None:
    r = await client.get("/v1/search-index")
    data = r.json()
    assert len(data["modules"]) == len(content.modules)
    assert len(data["units"]) == len(content.concepts)
    assert set(data["modules"][0]) == {"id", "title", "tagline", "mystery", "disciplines", "level", "hours"}
    assert set(data["units"][0]) == {"id", "title", "summary"}


def _basic(client_id: str, secret: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()}


async def test_bundle_is_only_for_the_website_server(client) -> None:
    assert (await client.get("/v1/content/bundle")).status_code == 401
    assert (await client.get("/v1/content/bundle", headers=_basic("hasesa-web", "wrong"))).status_code == 401
    assert (await client.get("/v1/content/bundle", headers=_basic("hasesa-mobile", ""))).status_code == 401
    r = await client.get("/v1/content/bundle", headers=_basic("hasesa-web", WEB_SECRET))
    assert r.status_code == 200
    data = r.json()
    assert len(data["modules"]) == len(content.modules)
    assert data["modules"][0]["guide"]
    assert r.headers["etag"].strip('"') == (await client.get("/v1/content/version")).json()["content"]
