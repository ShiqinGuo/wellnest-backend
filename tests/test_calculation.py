from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.assessment import Answers, CompleteAnswers
from app.domain.calculation import assess

SAMPLE = dict(
    sex="female",
    goal="lose",
    age=35,
    height_cm=165,
    weight_kg=75,
    target_weight_kg=65,
    activity="light",
)


def test_known_calculation():
    r = assess(CompleteAnswers.model_validate(SAMPLE), today=date(2026, 1, 1))
    assert r.bmi == 27.55
    assert r.resting_kcal == 1445
    assert r.maintenance_kcal == 1987
    assert r.suggested_kcal == 1689
    assert r.predicted_goal_date == date(2026, 9, 17)
    assert r.projection[0].weight_kg == 75
    assert r.projection[-1].weight_kg == 65
    assert all(
        a.date < b.date and a.weight_kg >= b.weight_kg
        for a, b in zip(r.projection, r.projection[1:], strict=False)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("age", 17),
        ("age", 81),
        ("age", True),
        ("age", 35.1),
        ("age", "35"),
        ("height_cm", 0),
        ("height_cm", 119),
        ("height_cm", 221),
        ("height_cm", float("nan")),
        ("height_cm", float("inf")),
        ("height_cm", "165; DROP TABLE users"),
        ("weight_kg", -1),
        ("weight_kg", 251),
        ("weight_kg", True),
        ("target_weight_kg", 80),
        ("target_weight_kg", 50),
        ("target_weight_kg", 0),
        ("sex", "unknown"),
        ("activity", "sometimes"),
    ],
)
def test_illegal_inputs(field, value):
    with pytest.raises(ValidationError):
        CompleteAnswers.model_validate(SAMPLE | {field: value})


@pytest.mark.parametrize("field", list(SAMPLE))
def test_missing_required(field):
    data = SAMPLE.copy()
    del data[field]
    with pytest.raises(ValidationError):
        CompleteAnswers.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("age", 18),
        ("age", 80),
        ("height_cm", 120),
        ("height_cm", 220),
        ("weight_kg", 35),
        ("weight_kg", 250),
    ],
)
def test_scalar_range_boundaries(field, value):
    assert Answers.model_validate({field: value})


def test_maintenance_and_gain():
    maintain = assess(
        CompleteAnswers.model_validate(SAMPLE | {"goal": "maintain", "target_weight_kg": 75}),
        today=date(2026, 1, 1),
    )
    assert maintain.predicted_goal_date == date(2026, 1, 1)
    assert len(maintain.projection) == 1
    gain = assess(
        CompleteAnswers.model_validate(SAMPLE | {"goal": "gain", "target_weight_kg": 80}),
        today=date(2026, 1, 1),
    )
    assert gain.suggested_kcal - gain.maintenance_kcal == 250


def test_unsupported_low_energy_loss():
    a = CompleteAnswers(
        sex="female",
        goal="lose",
        age=80,
        height_cm=150,
        weight_kg=45,
        target_weight_kg=44,
        activity="low",
    )
    with pytest.raises(ValueError, match="无法产生"):
        assess(a, today=date(2026, 1, 1))
