"""Read-only normalization of frozen pre-i18n result snapshots.

Only the v1 presentation format is reconstructed from its immutable input.
Numerical calculations are never rerun and persisted records are not rewritten.
Keep the v1 decision builder pinned if new decision rules are introduced.
"""

import json

from app.domain.assessment import Answers, Calculation
from app.domain.plan import PlanRuleVersion, build_plan
from app.domain.result_codes import BmiCategory, CalculationAssumption

LEGACY_BMI = {
    "偏低": BmiCategory.underweight,
    "参考范围内": BmiCategory.reference,
    "偏高": BmiCategory.overweight,
    "较高": BmiCategory.high,
}
LEGACY_ASSUMPTIONS = {
    "采用成人 Mifflin–St Jeor 公式及简化活动系数。": (CalculationAssumption.legacy_energy),
    "静息能量使用Mifflin–St Jeor公式；活动系数为简化分档。": (CalculationAssumption.resting_energy),
    "减重采用15%能量差，增重采用250 kcal/日；均为演示规则。": (
        CalculationAssumption.demo_energy_budget
    ),
    "曲线采用7700 kcal/kg的线性近似，未模拟代谢适应，日期不是承诺。": (
        CalculationAssumption.linear_projection
    ),
    "适用于18–80岁一般成人的演示估算，不用于孕期、哺乳期或医疗营养决策。": (
        CalculationAssumption.adult_scope
    ),
}


def load_calculation(raw: str, input_snapshot: str) -> Calculation:
    data = json.loads(raw)
    plan = data.get("plan_preview")
    if plan and "format_version" not in plan:
        if plan["rules_version"] != PlanRuleVersion.lifestyle_v1:
            raise ValueError("Unsupported legacy plan version")
        normalized = build_plan(Answers.model_validate_json(input_snapshot))
        if normalized is None:
            raise ValueError("Legacy plan is missing its lifestyle input snapshot")
        data["plan_preview"] = normalized.model_dump(mode="json")
    data["bmi_category"] = LEGACY_BMI.get(data["bmi_category"], data["bmi_category"])
    data["assumptions"] = [LEGACY_ASSUMPTIONS.get(value, value) for value in data["assumptions"]]
    return Calculation.model_validate(data)
