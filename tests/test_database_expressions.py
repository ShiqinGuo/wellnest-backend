import pytest
from sqlalchemy import select, text

from app.database import compile_statement
from app.models import Outbox


def test_driver_boundary_rejects_raw_sql_and_text_clause():
    for raw in ("not an expression", text("not an expression")):
        with pytest.raises(TypeError, match="SQLAlchemy expression"):
            compile_statement(raw)


def test_expanding_parameters_remain_bound_and_preserve_values():
    values = ["quote' and punctuation;", "second"]
    query, parameters = compile_statement(select(Outbox.id).where(Outbox.last_error.in_(values)))
    assert all(value not in query for value in values)
    assert parameters == tuple(values)
