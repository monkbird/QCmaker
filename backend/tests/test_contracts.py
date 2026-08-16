import pytest
from pydantic import ValidationError

from backend.app.models.contracts import CleaningRule, DataRow


def test_cleaning_rule_requires_target():
    with pytest.raises(ValidationError): CleaningRule(action="drop_rows")
    with pytest.raises(ValidationError): CleaningRule(action="median")


def test_data_row_rejects_non_json_value():
    with pytest.raises(ValidationError): DataRow(row_id="r1", values={"x": {"nested": True}})

