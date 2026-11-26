"""What the lab assistant knows about the page and the student.
Ported from hasesa-lab-web lib/chat-context.ts.

The assistant lives on course pages, and each page is a context:
  "m:<module>"          a module page
  "m:<module>/<step>"   a step page
  "c:<concept>"         a concept unit page
The page decides the context; the student never picks it.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.content.loader import get_content, module_units
from hasesa_api.content.models import Concept, McqProblem
from hasesa_api.learning import service as learning
from hasesa_api.models import StepProgress


@dataclass(frozen=True)
class Parsed:
    kind: str  # concept | module | step
    concept_id: str = ""
    module_id: str = ""
    step_id: str = ""


def parse(value: object) -> Parsed | None:
    if not isinstance(value, str):
        return None
    c = get_content()
    if value.startswith("c:"):
        return Parsed("concept", concept_id=value[2:]) if value[2:] in c.concepts else None
    if value.startswith("m:"):
        module_id, sep, step_id = value[2:].partition("/")
        m = c.module(module_id)
        if m is None:
            return None
        if not sep:
            return Parsed("module", module_id=module_id)
        if any(s.id == step_id for s in m.steps):
            return Parsed("step", module_id=module_id, step_id=step_id)
    return None


def is_valid_context(value: object) -> bool:
    return parse(value) is not None


def _concept_text(c: Concept) -> str:
    return f"## Concept unit: {c.title}\n{c.summary}\n\n{c.body}"


@dataclass(frozen=True)
class Grounding:
    title: str
    text: str


def grounding_for(value: object) -> Grounding | None:
    """What the page is about, for the system prompt."""
    p = parse(value)
    if p is None:
        return None
    content = get_content()
    if p.kind == "concept":
        c = content.concepts[p.concept_id]
        return Grounding(f'the concept unit "{c.title}"', _concept_text(c))
    m = content.module(p.module_id)
    assert m is not None
    safety = "\n".join(f"- {s}" for s in m.safety)
    header = (
        f"# Module: {m.title}: {m.tagline}\nThe mystery: {m.hook}\nGoal: {m.goal}\nWhat they build: {m.whatYouBuild}"
        f"\n\n## Safety rules for this module\n{safety}"
    )
    if p.kind == "module":
        steps = "\n".join(f"{i + 1}. {s.title} ({s.minutes} min)" for i, s in enumerate(m.steps))
        return Grounding(f"the {m.title} module", f"{header}\n\n## Steps\n{steps}\n\n## Overview\n{m.body}")
    index = next(i for i, s in enumerate(m.steps) if s.id == p.step_id)
    step = m.steps[index]
    units = "\n\n".join(_concept_text(content.concepts[u]) for u in step.units if u in content.concepts)
    return Grounding(
        f"{m.title}, step {index + 1} ({step.title})",
        f"{header}\n\n## Step {index + 1} of {len(m.steps)}: {step.title}\n{step.body}\n\n{units}",
    )


async def student_context_for(db: AsyncSession, user_id: str, value: object) -> str | None:
    """What this student has done on this page, so the assistant can meet them
    where they are. Never includes answer keys."""
    p = parse(value)
    if p is None:
        return None
    content = get_content()

    if p.kind == "step":
        row = (
            await db.execute(
                select(StepProgress.notes, StepProgress.done).where(
                    StepProgress.user_id == user_id,
                    StepProgress.module_id == p.module_id,
                    StepProgress.step_id == p.step_id,
                )
            )
        ).first()
        lines = [f"- This step is {'marked done' if row and row.done else 'not marked done yet'}."]
        if row and row.notes:
            lines.append(f'- Their lab notebook for this step says:\n"""\n{row.notes[:2000]}\n"""')
        return "\n".join(lines)

    if p.kind == "concept":
        c = content.concepts[p.concept_id]
        attempts = await learning.get_attempts(db, user_id, [c.id])
        stuck = []
        for n, prob in enumerate(c.problems, start=1):
            mine = [a for a in attempts if a.question_id == prob.id]
            if not mine or any(a.correct for a in mine):
                continue
            last = mine[-1].answer
            if isinstance(prob, McqProblem):
                shown = (
                    prob.choices[int(last)]
                    if last.isascii() and last.isdigit() and int(last) < len(prob.choices)
                    else last
                )
            else:
                shown = f"{last} {prob.unit}" if prob.unit else last
            tries = "try" if len(mine) == 1 else "tries"
            stuck.append(f'- Problem {n} ("{prob.q}"): {len(mine)} wrong {tries}, last answer "{shown}".')
        solved = sum(1 for prob in c.problems if any(a.question_id == prob.id and a.correct for a in attempts))
        return "\n".join([f"- They have solved {solved} of {len(c.problems)} problems in this unit.", *stuck])

    m = content.module(p.module_id)
    assert m is not None
    s = await learning.get_student_state(db, user_id)
    enrollment = next((e for e in s.enrollments if e.module_id == m.id), None)
    signoff = next((x for x in s.signoffs if x.module_id == m.id), None)
    done_ids = {x.step_id for x in s.steps if x.module_id == m.id and x.done}
    unit_ids = module_units(m)
    units = [u for u in s.units if u.unit_id in unit_ids]
    status = "completed" if signoff else enrollment.status if enrollment else "not-started"
    steps_done = sum(1 for st in m.steps if st.id in done_ids)
    units_done = sum(1 for u in units if u.status in ("completed", "tested_out"))
    nxt = next((st for st in m.steps if st.id not in done_ids), None)
    return (
        f"- Module status: {status}. {steps_done} of {len(m.steps)} steps done, "
        f"{units_done} of {len(unit_ids)} concept units done." + (f' Next step: "{nxt.title}".' if nxt else "")
    )
