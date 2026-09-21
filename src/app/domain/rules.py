from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.domain.enums import Activity, RuleVersion, Sex

CM_PER_METRE = 100
DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class InputRules:
    age_min: int = 18
    age_max: int = 80
    height_min_cm: int = 120
    height_max_cm: int = 220
    weight_min_kg: int = 35
    weight_max_kg: int = 250
    max_target_change_ratio: float = 0.25
    target_bmi_min: float = 18.5
    target_bmi_max: float = 40


@dataclass(frozen=True)
class WellnessRules:
    version: RuleVersion = RuleVersion.wellness_v2
    loss_energy_ratio: float = 0.85
    gain_surplus_kcal: int = 250
    kcal_per_kg: int = 7700
    max_prediction_days: int = 730
    max_projection_intervals: int = 24
    bmi_underweight: float = 18.5
    bmi_overweight: float = 25
    bmi_obesity: float = 30
    weight_coefficient: float = 10
    height_coefficient: float = 6.25
    age_coefficient: float = 5
    bmi_precision: int = 2
    weight_precision: int = 1
    weekly_change_precision: int = 2
    activity_factors: Mapping[Activity, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                Activity.low: 1.2,
                Activity.light: 1.375,
                Activity.moderate: 1.55,
                Activity.high: 1.725,
            }
        )
    )
    minimum_energy: Mapping[Sex, int] = field(
        default_factory=lambda: MappingProxyType(
            {
                Sex.male: 1500,
                Sex.female: 1200,
            }
        )
    )
    sex_coefficients: Mapping[Sex, int] = field(
        default_factory=lambda: MappingProxyType(
            {
                Sex.male: 5,
                Sex.female: -161,
            }
        )
    )


@dataclass(frozen=True)
class JevRules:
    version: RuleVersion = RuleVersion.guidance_v3
    model: str = "jev-latest"
    timeout_seconds: float = 8
    minimum_confidence: float = 0.6
    probability_tolerance: float = 0.02
    effort_min: int = 0
    effort_max: int = 2
    gradual_effort_threshold: float = 1


INPUT_RULES = InputRules()
WELLNESS_V2 = WellnessRules()
JEV_RULES = JevRules()
