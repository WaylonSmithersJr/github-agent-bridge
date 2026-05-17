from github_agent_bridge import reader_run


def test_reader_run_builds_imap_args_without_mark_seen(monkeypatch):
    captured = {}

    def fake_cli_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(reader_run, "cli_main", fake_cli_main)
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_DB", "/tmp/bridge.sqlite3")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_POLICY", "/tmp/policy.json")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_EMAIL", "bot@example.com")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_PASSWORD", "secret")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_IMAP_PORT", "993")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_MAILBOX", "GitHub")
    monkeypatch.delenv("GITHUB_AGENT_BRIDGE_MARK_SEEN", raising=False)

    assert reader_run.main() == 0

    assert captured["argv"] == [
        "--db",
        "/tmp/bridge.sqlite3",
        "--policy",
        "/tmp/policy.json",
        "read-imap-once",
        "--imap-host",
        "imap.example.com",
        "--imap-port",
        "993",
        "--email",
        "bot@example.com",
        "--password",
        "secret",
        "--mailbox",
        "GitHub",
    ]


def test_reader_run_adds_mark_seen_only_when_enabled(monkeypatch):
    captured = {}

    def fake_cli_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(reader_run, "cli_main", fake_cli_main)
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_EMAIL", "bot@example.com")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_PASSWORD", "secret")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_MARK_SEEN", "--mark-seen")

    assert reader_run.main() == 0
    assert captured["argv"][-1] == "--mark-seen"


def test_reader_run_quotes_mailbox_with_spaces(monkeypatch):
    captured = {}

    def fake_cli_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(reader_run, "cli_main", fake_cli_main)
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_EMAIL", "bot@example.com")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_PASSWORD", "secret")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_MAILBOX", "[Gmail]/All Mail")

    assert reader_run.main() == 0
    assert captured["argv"][captured["argv"].index("--mailbox") + 1] == '"[Gmail]/All Mail"'


def test_reader_run_keeps_prequoted_mailbox(monkeypatch):
    captured = {}

    def fake_cli_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(reader_run, "cli_main", fake_cli_main)
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_EMAIL", "bot@example.com")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_PASSWORD", "secret")
    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_MAILBOX", '"[Gmail]/All Mail"')

    assert reader_run.main() == 0
    assert captured["argv"][captured["argv"].index("--mailbox") + 1] == '"[Gmail]/All Mail"'


def test_reader_run_requires_email_and_password(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_AGENT_BRIDGE_EMAIL", raising=False)
    monkeypatch.delenv("GITHUB_AGENT_BRIDGE_PASSWORD", raising=False)

    assert reader_run.main() == 2
    assert "GITHUB_AGENT_BRIDGE_EMAIL" in capsys.readouterr().err
