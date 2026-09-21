from enum import StrEnum


class BmiCategory(StrEnum):
    underweight = "underweight"
    reference = "reference"
    overweight = "overweight"
    high = "high"


class CalculationAssumption(StrEnum):
    legacy_energy = "legacy_energy"
    resting_energy = "resting_energy"
    demo_energy_budget = "demo_energy_budget"
    linear_projection = "linear_projection"
    adult_scope = "adult_scope"


class ResultSummary(StrEnum):
    personal_start = "personal_start"
