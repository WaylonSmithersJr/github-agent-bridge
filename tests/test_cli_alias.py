from github_agent_bridge import cli
from github_agent_bridge.queue import JobQueue


def test_parser_program_uses_invoked_binary_name(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["/usr/local/bin/gab", "status"])
    parser = cli.build_parser()
    assert parser.prog == "gab"


def test_feedback_rules_cli_lists_rules(tmp_path, capsys):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)
    cli.main(["--db", str(db), "feedback-rules", "--scope", "repo:gisce/erp"])

    captured = capsys.readouterr()
    assert '"rules": []' in captured.out


def test_feedback_rule_add_cli_creates_rule(tmp_path, capsys):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    cli.main([
        "--db",
        str(db),
        "feedback-rule-add",
        "--scope",
        "repo:gisce/erp",
        "--type",
        "style_preference",
        "--rule",
        "Answer with concrete evidence.",
        "--confidence",
        "0.8",
    ])

    captured = capsys.readouterr()
    assert '"rule": {' in captured.out
    assert "Answer with concrete evidence." in captured.out


def test_feedback_events_cli_lists_events(tmp_path, capsys):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    cli.main(["--db", str(db), "feedback-events", "--scope", "repo:gisce/erp"])

    captured = capsys.readouterr()
    assert '"events": []' in captured.out
