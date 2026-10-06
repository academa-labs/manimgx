"""Only meaningful RGB comparison budgets can be persisted by the review server."""

import pytest
from pydantic import ValidationError
from tests.integration.review import app as panel


@pytest.mark.parametrize("value", [-1, 256, float("inf"), float("nan")])
def test_review_settings_reject_impossible_channel_error_budgets(value: float) -> None:
    with pytest.raises(ValidationError):
        panel.SettingsIn(metric="max", tolerance=value)
