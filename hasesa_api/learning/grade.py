"""Answer checking and unit scoring. Ported from hasesa-lab-web lib/content/grade.ts.

The behaviour must match the website exactly (the web keeps its own copy as a
fallback for a while), including JavaScript's number parsing and formatting.
"""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from hasesa_api.content.models import McqProblem, NumericProblem

Problem = McqProblem | NumericProblem

# Pass mark for testing out of a concept unit.
TEST_OUT_PASS = 0.8

# [0-9], not \d: Python's \d also matches non-ASCII digits, JavaScript's doesn't.
_SCI = re.compile(r"^([-+]?[0-9]*\.?[0-9]+)\s*[x×*]\s*10\s*\^\s*([-+]?[0-9]+)$", re.IGNORECASE)
_PLAIN = re.compile(r"^[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)(e[-+]?[0-9]+)?$", re.IGNORECASE)
_DIGITS = re.compile(r"^[0-9]+$")


def js_round(x: float) -> int:
    """JavaScript's Math.round: halves round up, not to even."""
    return math.floor(x + 0.5)


def parse_number(raw: str) -> float | None:
    """Read a number the way students type it: "1500", "1,500", "1.5e3",
    "1.5 x 10^3" or "1.5×10^3". Returns None when it isn't a number."""
    s = re.sub(r"\s+", " ", raw.strip().replace(",", ""))
    if not s:
        return None
    sci = _SCI.match(s)
    if sci:
        mantissa = float(sci[1])
        try:
            scale = 10.0 ** int(sci[2])
        except OverflowError:
            scale = math.inf
        # As in JavaScript, an overflow gives Infinity (or NaN for 0 × 10^400), never an error.
        return mantissa * scale
    if not _PLAIN.match(s):
        return None
    n = float(s)
    return n if math.isfinite(n) else None


def is_correct(p: Problem, answer: str) -> bool:
    if isinstance(p, McqProblem):
        a = answer.strip()
        return bool(_DIGITS.match(a)) and int(a) == p.answerIndex
    n = parse_number(answer)
    if n is None:
        return False
    if p.answer == 0:
        return abs(n) < 1e-9
    return (abs(n - p.answer) / abs(p.answer)) * 100 <= p.tolerancePct + 1e-9


def answer_text(p: Problem) -> str:
    """The answer to show once a student has seen the explanation."""
    if isinstance(p, McqProblem):
        return p.choices[p.answerIndex]
    return f"{format_number(p.answer)} {p.unit}" if p.unit else format_number(p.answer)


def _to_exponential(n: float, digits: int) -> str:
    """JavaScript's Number.prototype.toExponential(digits)."""
    sign = "-" if n < 0 else ""
    d = abs(Decimal(n))
    if d == 0:
        return f"{sign}{Decimal(0).quantize(Decimal(1).scaleb(-digits))}e+0"
    exp = d.adjusted()
    mantissa = d.scaleb(-exp).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if mantissa >= 10:
        exp += 1
        mantissa = d.scaleb(-exp).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{sign}{mantissa}e{'+' if exp >= 0 else '-'}{abs(exp)}"


def _js_string(x: float) -> str:
    """JavaScript's String(number) for values between 1e-7 and 1e21 (the only ones used here)."""
    if x.is_integer():
        return str(int(x))
    return repr(x)


def _to_precision_number(n: float, digits: int) -> float:
    """Number(n.toPrecision(digits)) in JavaScript."""
    if n == 0:
        return 0.0
    d = abs(Decimal(n))
    rounded = d.quantize(Decimal(1).scaleb(d.adjusted() - digits + 1), rounding=ROUND_HALF_UP)
    return float(rounded) if n > 0 else -float(rounded)


def format_number(n: float) -> str:
    a = abs(n)
    if a != 0 and (a >= 1e6 or a < 1e-3):
        return _to_exponential(n, 2).replace("e+", " × 10^").replace("e-", " × 10^-")
    return _js_string(_to_precision_number(n, 4))


class AttemptLike(Protocol):
    question_id: str
    correct: bool
    created_at: datetime


@dataclass(frozen=True)
class UnitScore:
    first_try_pct: int
    all_correct: bool
    answered: int


def score_unit(problem_ids: list[str], attempts: Iterable[AttemptLike]) -> UnitScore:
    """Score a unit from a student's attempts: the share of problems they got
    right on their first try, and whether every problem has been answered
    correctly at some point (which is what "completed" means)."""
    by_q: dict[str, list[AttemptLike]] = {}
    for a in attempts:
        if a.question_id not in problem_ids:
            continue
        by_q.setdefault(a.question_id, []).append(a)
    first_right = 0
    ever_right = 0
    for pid in problem_ids:
        tries = sorted(by_q.get(pid, []), key=lambda a: a.created_at)
        if tries and tries[0].correct:
            first_right += 1
        if any(a.correct for a in tries):
            ever_right += 1
    n = len(problem_ids) or 1
    return UnitScore(
        first_try_pct=js_round(first_right / n * 100),
        all_correct=len(problem_ids) > 0 and ever_right == len(problem_ids),
        answered=len(by_q),
    )
