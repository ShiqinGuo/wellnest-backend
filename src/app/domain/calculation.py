import math
from datetime import date, timedelta
from decimal import Decimal

from app.domain.assessment import Calculation, CompleteAnswers, Goal, ProjectionPoint
from app.domain.result_codes import BmiCategory, CalculationAssumption
from app.domain.rules import CM_PER_METRE, DAYS_PER_WEEK, WELLNESS_V2, WellnessRules


def assess(
    answers: CompleteAnswers, *, today: date, rules: WellnessRules = WELLNESS_V2
) -> Calculation:
    """Deterministic educational estimate, not a clinical prediction.

    Mifflin–St Jeor REE; activity multipliers and energy-budget projection are
    explicit product assumptions. A static 7700 kcal/kg model does not model
    metabolic adaptation. No claim to reproduce NIDDK's dynamic model.
    """
    bmi = answers.weight_kg / (answers.height_cm / CM_PER_METRE) ** 2
    category = (
        BmiCategory.underweight
        if bmi < rules.bmi_underweight
        else BmiCategory.reference
        if bmi < rules.bmi_overweight
        else BmiCategory.overweight
        if bmi < rules.bmi_obesity
        else BmiCategory.high
    )
    resting = (
        rules.weight_coefficient * answers.weight_kg
        + rules.height_coefficient * answers.height_cm
        - rules.age_coefficient * answers.age
        + rules.sex_coefficients[answers.sex]
    )
    maintenance = round(resting * rules.activity_factors[answers.activity])
    floor = rules.minimum_energy[answers.sex]
    if answers.goal == Goal.lose:
        suggested = max(floor, round(maintenance * rules.loss_energy_ratio))
        daily_change = max(0, maintenance - suggested) / rules.kcal_per_kg
    elif answers.goal == Goal.gain:
        suggested = maintenance + rules.gain_surplus_kcal
        daily_change = rules.gain_surplus_kcal / rules.kcal_per_kg
    else:
        suggested = maintenance
        daily_change = 0
    difference = answers.target_weight_kg - answers.weight_kg
    if difference and daily_change == 0:
        raise ValueError("当前数据无法产生适用的目标预测，请调整目标或寻求专业建议")
    # Decimal arithmetic prevents an exact 154-day budget becoming
    # 154.00000000000003 and being rounded up to 155 days.
    exact_difference = abs(Decimal(str(answers.target_weight_kg)) - Decimal(str(answers.weight_kg)))
    energy_gap = abs(suggested - maintenance)
    days = (
        math.ceil(exact_difference * Decimal(str(rules.kcal_per_kg)) / energy_gap)
        if difference
        else 0
    )
    if days > rules.max_prediction_days:
        raise ValueError("目标预测超过本工具两年的估算范围，请选择更小的阶段目标")
    goal_date = today + timedelta(days=days)
    intervals = max(1, min(rules.max_projection_intervals, math.ceil(days / DAYS_PER_WEEK)))
    points = (
        [
            ProjectionPoint(
                date=today + timedelta(days=round(days * i / intervals)),
                weight_kg=round(
                    answers.weight_kg + difference * i / intervals, rules.weight_precision
                ),
            )
            for i in range(intervals + 1)
        ]
        if days
        else [ProjectionPoint(date=today, weight_kg=answers.weight_kg)]
    )
    return Calculation(
        calculated_on=today,
        algorithm_version=rules.version,
        bmi=round(bmi, rules.bmi_precision),
        bmi_category=category,
        resting_kcal=round(resting),
        maintenance_kcal=maintenance,
        suggested_kcal=suggested,
        predicted_goal_date=goal_date,
        weekly_change_kg=round(daily_change * DAYS_PER_WEEK, rules.weekly_change_precision),
        projection=points,
        assumptions=[
            CalculationAssumption.resting_energy,
            CalculationAssumption.demo_energy_budget,
            CalculationAssumption.linear_projection,
            CalculationAssumption.adult_scope,
        ],
    )
