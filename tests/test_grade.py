"""Answer checking. Ported from hasesa-lab-web lib/content/grade.test.ts, plus
cases that pin down JavaScript's number handling (the web shows the same text)."""

import math
from dataclasses import dataclass
from datetime import datetime

import pytest

from hasesa_api.content.models import McqProblem, NumericProblem
from hasesa_api.learning.grade import answer_text, format_number, is_correct, js_round, parse_number, score_unit

numeric = NumericProblem(id="f", type="numeric", q="f?", answer=1.027e6, tolerancePct=2, unit="Hz", explanation="…")
mcq = McqProblem(id="m", type="mcq", q="?", choices=["a", "b", "c"], answerIndex=1, explanation="…")


@pytest.mark.parametrize(
    ("raw", "n"),
    [
        ("1500", 1500),
        ("1,500", 1500),
        (" 1.5e3 ", 1500),
        ("1.5 x 10^3", 1500),
        ("1.5×10^-3", 0.0015),
        ("-0.25", -0.25),
        (".5", 0.5),
        ("1.", 1),
        ("+2", 2),
        ("3 X 10 ^ 2", 300),
        ("2*10^2", 200),
    ],
)
def test_parse_number_reads(raw: str, n: float) -> None:
    assert parse_number(raw) == pytest.approx(n)


@pytest.mark.parametrize("raw", ["", "abc", "12abc", "1.2.3", "e5", "1e999", "١٢", "1 . 5", "0x10", "inf", "nan"])
def test_parse_number_rejects(raw: str) -> None:
    assert parse_number(raw) is None


def test_parse_number_overflow_is_infinity_like_javascript() -> None:
    assert parse_number("2 x 10^400") == math.inf
    assert math.isnan(parse_number("0 x 10^400"))  # type: ignore[arg-type]
    assert not is_correct(numeric, "2 x 10^400")


def test_numeric_answers_within_tolerance() -> None:
    assert is_correct(numeric, "1.03e6")
    assert is_correct(numeric, "1,010,000")  # 1.7% off


def test_numeric_answers_outside_tolerance() -> None:
    assert not is_correct(numeric, "1.1e6")
    assert not is_correct(numeric, "1,000,000")  # 2.6% off
    assert not is_correct(numeric, "lots")


def test_multiple_choice_by_index() -> None:
    assert is_correct(mcq, "1")
    assert is_correct(mcq, " 01 ")
    assert not is_correct(mcq, "0")
    assert not is_correct(mcq, "b")
    assert not is_correct(mcq, "1.0")


def test_answer_of_zero() -> None:
    zero = numeric.model_copy(update={"answer": 0})
    assert is_correct(zero, "0")
    assert not is_correct(zero, "0.1")


def test_answer_text() -> None:
    assert answer_text(mcq) == "b"
    assert answer_text(numeric) == "1.03 × 10^6 Hz"
    assert answer_text(numeric.model_copy(update={"unit": None})) == "1.03 × 10^6"


@pytest.mark.parametrize(
    ("n", "text"),
    [
        # Expected values are what JavaScript's formatNumber prints.
        (0, "0"),
        (1500, "1500"),
        (12345.6, "12350"),
        (999999.4, "1000000"),
        (0.0012346, "0.001235"),
        (2.5, "2.5"),
        (-3.14159, "-3.142"),
        (9.81, "9.81"),
        (1.125e6, "1.13 × 10^6"),
        (6.02e23, "6.02 × 10^23"),
        (-1.6e-19, "-1.60 × 10^-19"),
        (0.000999, "9.99 × 10^-4"),
        (9.999e6, "1.00 × 10^7"),
    ],
)
def test_format_number_matches_javascript(n: float, text: str) -> None:
    assert format_number(n) == text


def test_js_round_rounds_halves_up() -> None:
    assert js_round(50.5) == 51
    assert js_round(62.5) == 63
    assert js_round(66.66) == 67


@dataclass
class A:
    question_id: str
    correct: bool
    created_at: datetime


def t(s: int) -> datetime:
    return datetime(2026, 11, 6, 12, 0, s)


def test_score_unit_first_tries_and_completion() -> None:
    r = score_unit(["a", "b"], [A("a", False, t(1)), A("a", True, t(2)), A("b", True, t(3))])
    assert (r.first_try_pct, r.all_correct, r.answered) == (50, True, 2)


def test_score_unit_out_of_order_attempts_use_the_earliest() -> None:
    r = score_unit(["a"], [A("a", True, t(2)), A("a", False, t(1))])
    assert r.first_try_pct == 0 and r.all_correct


def test_score_unit_not_complete_until_every_problem_is_right() -> None:
    r = score_unit(["a", "b"], [A("a", True, t(1))])
    assert not r.all_correct
    assert r.first_try_pct == 50


def test_score_unit_ignores_removed_problems() -> None:
    r = score_unit(["a"], [A("gone", True, t(1))])
    assert (r.first_try_pct, r.all_correct, r.answered) == (0, False, 0)
