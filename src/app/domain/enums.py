from enum import StrEnum


class Sex(StrEnum):
    female = "female"
    male = "male"


class Goal(StrEnum):
    lose = "lose"
    maintain = "maintain"
    gain = "gain"


class Activity(StrEnum):
    low = "low"
    light = "light"
    moderate = "moderate"
    high = "high"


class AssessmentStatus(StrEnum):
    draft = "draft"
    completed = "completed"


class AssessmentEvent(StrEnum):
    edit = "edit"
    submit = "submit"


class SubscriptionStatus(StrEnum):
    inactive = "inactive"
    active = "active"


class SubscriptionEvent(StrEnum):
    activate = "activate"


class Step(StrEnum):
    welcome = "welcome"
    sex = "sex"
    goal = "goal"
    age = "age"
    height = "height"
    weight = "weight"
    target = "target"
    activity = "activity"
    review = "review"
    result = "result"
    goal_feedback = "goal_feedback"
    activity_feedback = "activity_feedback"
    target_feedback = "target_feedback"
    secondary_goals = "secondary_goals"
    experience = "experience"
    daily_activity = "daily_activity"
    limitations = "limitations"
    sleep = "sleep"
    energy = "energy"
    meal_rhythm = "meal_rhythm"
    food_habits = "food_habits"
    barrier = "barrier"
    time_window = "time_window"
    movement_feedback = "movement_feedback"
    habits_feedback = "habits_feedback"


class FlowVersion(StrEnum):
    legacy = "wellness-v1"
    guided = "guided-v2"
    lifestyle = "lifestyle-v3"


class PlanId(StrEnum):
    demo = "wellnest-demo"


class RuleVersion(StrEnum):
    wellness_v1 = "wellness-v1"
    wellness_v2 = "wellness-v2"
    guidance_v1 = "plan-guidance-v1"
    guidance_v2 = "plan-guidance-v2"
    guidance_v3 = "plan-guidance-v3"


class ResultAccess(StrEnum):
    free = "free"
    member = "member"


class GuidanceStatus(StrEnum):
    ready = "ready"
    uncertain = "uncertain"
    unavailable = "unavailable"
    disabled = "disabled"


class GuidanceEvent(StrEnum):
    retry = "retry"


class SecondaryGoal(StrEnum):
    energy = "energy"
    mobility = "mobility"
    routine = "routine"
    strength = "strength"


class Experience(StrEnum):
    beginner = "beginner"
    returning = "returning"
    regular = "regular"


class DailyActivity(StrEnum):
    seated = "seated"
    mixed = "mixed"
    on_feet = "on_feet"


class Limitation(StrEnum):
    back = "back"
    knees = "knees"
    none = "none"


class Sleep(StrEnum):
    short = "short"
    variable = "variable"
    rested = "rested"


class Energy(StrEnum):
    low_energy = "low_energy"
    afternoon_dip = "afternoon_dip"
    steady = "steady"


class MealRhythm(StrEnum):
    regular_meals = "regular_meals"
    skipped_meals = "skipped_meals"
    irregular_meals = "irregular_meals"


class FoodHabit(StrEnum):
    late_snacks = "late_snacks"
    sweet_drinks = "sweet_drinks"
    sweets = "sweets"
    none = "none"


class Barrier(StrEnum):
    time = "time"
    motivation = "motivation"
    unsure = "unsure"
    no_barrier = "no_barrier"


class TimeWindow(StrEnum):
    morning = "morning"
    midday = "midday"
    evening = "evening"
    varies = "varies"
