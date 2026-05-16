import subprocess

from github_agent_bridge import feedback
from github_agent_bridge.models import GitHubContext, Notification


def notification():
    return Notification(
        uid=1,
        message_id="<1@github.com>",
        subject="Re: [gisce/erp] PR",
        from_addr="notifications@github.com",
        body="El primer bloc es veu clarament que ho ha escrit una IA. https://github.com/gisce/erp/pull/1#issuecomment-10",
    )


def context():
    return GitHubContext(["https://github.com/gisce/erp/pull/1#issuecomment-10"], "gisce/erp", 1, comment_id=10)


def test_capture_feedback_invokes_local_learner(tmp_path, monkeypatch):
    learner = tmp_path / "learner"
    learner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    learner.chmod(0o755)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNER", str(learner))
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNING", "1")
    monkeypatch.setattr("subprocess.run", fake_run)

    assert feedback.capture_feedback(notification(), context(), "reply_comment", "auto_trusted", "review_only")

    args, kwargs = calls[0]
    assert args[:3] == [str(learner), "ingest", "--source"]
    assert "github-agent-bridge" in args
    assert "--scope" in args
    assert args[args.index("--scope") + 1] == "repo:gisce/erp"
    assert "--event-id" in args
    assert args[args.index("--event-id") + 1].startswith("github-agent-bridge-")
    assert kwargs["check"] is False


def test_capture_feedback_ignores_non_actionable_decisions(tmp_path, monkeypatch):
    learner = tmp_path / "learner"
    learner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    learner.chmod(0o755)
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNER", str(learner))
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNING", "1")

    assert feedback.capture_feedback(notification(), context(), "archive_notification", "auto", "work_allowed") is False
