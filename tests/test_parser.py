from github_agent_bridge.parser import classify_github_action, classify_work_intent, extract_github_context


def test_extract_review_comment_context():
    ctx = extract_github_context("@pilipilisbot mira https://github.com/gisce/erp/pull/27592#discussion_r3195891007")
    assert ctx.repo == "gisce/erp"
    assert ctx.issue_number == 27592
    assert ctx.review_comment_id == 3195891007
    assert ctx.work_key == "gisce/erp#27592"


def test_extract_commit_comment_context():
    ctx = extract_github_context("@pilipilisbot mira https://github.com/pilipilisbot/github-agent-bridge/commit/fbd7bc190e4f63b00785671144e834a3c99c3fb1#r185806568")
    assert ctx.repo == "pilipilisbot/github-agent-bridge"
    assert ctx.issue_number is None
    assert ctx.commit_sha == "fbd7bc190e4f63b00785671144e834a3c99c3fb1"
    assert ctx.commit_comment_id == 185806568
    assert ctx.target_kind == "commit_comment"
    assert ctx.work_key == "pilipilisbot/github-agent-bridge@fbd7bc190e4f"


def test_extract_workflow_run_context():
    ctx = extract_github_context("Run failed: https://github.com/pilipilisbot/github-agent-bridge/actions/runs/26325244472")
    assert ctx.repo == "pilipilisbot/github-agent-bridge"
    assert ctx.workflow_run_id == 26325244472
    assert ctx.issue_number is None
    assert ctx.target_kind == "workflow_run"
    assert ctx.work_key == "pilipilisbot/github-agent-bridge/actions/runs/26325244472"


def test_extract_pr_comment_context_before_workflow_run_link():
    ctx = extract_github_context(
        'Screenshot https://github.com/user-attachments/assets/5ac382c7-e004-429b-8e35-7feb3e8f9c6f"\n'
        "Run https://github.com/gisce/webclient/actions/runs/26408091899)\n"
        "Comment https://github.com/gisce/webclient/pull/3333#issuecomment-4535411370"
    )

    assert ctx.repo == "gisce/webclient"
    assert ctx.issue_number == 3333
    assert ctx.comment_id == 4535411370
    assert ctx.workflow_run_id is None
    assert ctx.target_kind == "issue_comment"
    assert ctx.work_key == "gisce/webclient#3333"
    assert ctx.short_url == "https://github.com/gisce/webclient/pull/3333#issuecomment-4535411370"
    assert "https://github.com/gisce/webclient/actions/runs/26408091899" in ctx.urls


def test_mentions_are_actionable():
    assert classify_github_action("Re: [x] PR", "@pilipilisbot fes-ho", {"pilipilisbot"}) == "reply_comment"
    assert classify_github_action("Re: [x] PR", "You are receiving this because you were mentioned.") == "reply_comment"


def test_workflow_run_failed_is_actionable_without_mention():
    subject = "[pilipilisbot/github-agent-bridge] Run failed: tests - main"
    body = "View run: https://github.com/pilipilisbot/github-agent-bridge/actions/runs/26325244472"

    assert classify_github_action(subject, body) == "workflow_run_failed"
    assert classify_work_intent(subject, body) == "work_allowed"


def test_copilot_comment_is_actionable():
    assert classify_github_action("Re: [x] PR", "@Copilot commented on this pull request.") == "reply_comment"


def test_review_only_intent():
    assert classify_work_intent("", "com veus els canvis? fes-ne una review") == "review_only"
    assert classify_work_intent("", "fes-ne una review i aplica el fix") == "work_allowed"


def test_review_request_uses_formal_review_flow():
    subject = "Re: [gisce/erp] Permitir caller en los dominios (PR #27315)"
    body = "ecarreras requested review from @pilipilisbot on this pull request."

    assert classify_github_action(subject, body, {"pilipilisbot"}) == "submit_review"
    assert classify_work_intent(subject, body, {"pilipilisbot"}) == "review_only"


def test_pr_review_followup_is_read_only_without_explicit_implementation():
    subject = "Re: [gisce/erp] Permitir caller en los dominios (PR #27315)"
    body = "@pilipilisbot però la transacció en què s'executa que entra per eval_domain és amb una transacció readonly"

    assert classify_github_action(subject, body, {"pilipilisbot"}) == "reply_comment"
    assert classify_work_intent(subject, body, {"pilipilisbot"}) == "review_only"


def test_pr_followup_can_still_request_explicit_implementation():
    subject = "Re: [gisce/erp] Permitir caller en los dominios (PR #27315)"
    body = "@pilipilisbot aplica el canvi i fes push"

    assert classify_github_action(subject, body, {"pilipilisbot"}) == "reply_comment"
    assert classify_work_intent(subject, body) == "work_allowed"


def test_pr_assignment_allows_work():
    subject = "Re: [gisce/erp] Permitir caller en los dominios (PR #27315)"
    body = "ecarreras assigned @pilipilisbot to this pull request."

    assert classify_github_action(subject, body, {"pilipilisbot"}) == "open_issue"
    assert classify_work_intent(subject, body, {"pilipilisbot"}) == "work_allowed"
