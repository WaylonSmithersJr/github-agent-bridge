from pathlib import Path

from github_agent_bridge import cli


def test_parser_program_uses_invoked_binary_name(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["/usr/local/bin/gab", "status"])
    parser = cli.build_parser()
    assert parser.prog == "gab"
