from github_agent_bridge.parser import classify_github_action, classify_work_intent, extract_github_context


def test_extract_review_comment_context():
    ctx = extract_github_context("@pilipilisbot mira https://github.com/gisce/erp/pull/27592#discussion_r3195891007")
    assert ctx.repo == "gisce/erp"
    assert ctx.issue_number == 27592
    assert ctx.review_comment_id == 3195891007
    assert ctx.work_key == "gisce/erp#27592"


def test_mentions_are_actionable():
    assert classify_github_action("Re: [x] PR", "@pilipilisbot fes-ho") == "reply_comment"
    assert classify_github_action("Re: [x] PR", "You are receiving this because you were mentioned.") == "reply_comment"


def test_copilot_comment_is_actionable():
    assert classify_github_action("Re: [x] PR", "@Copilot commented on this pull request.") == "reply_comment"


def test_review_only_intent():
    assert classify_work_intent("", "com veus els canvis? fes-ne una review") == "review_only"
    assert classify_work_intent("", "fes-ne una review i aplica el fix") == "work_allowed"
