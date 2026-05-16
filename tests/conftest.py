import pytest


@pytest.fixture(autouse=True)
def disable_feedback_learning_by_default(monkeypatch):
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNING", "0")
