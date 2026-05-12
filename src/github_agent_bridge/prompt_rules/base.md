[AUTO_GITHUB_WORK]
repo={repo}
thread={thread}
action={action}
work_intent={work_intent}
url={url}
message_id={message_id}
subject={subject}

Trusted GitHub event detected. Load the full issue/PR/comments context before acting.
Do real work for this thread; do not stop at ack-only. If blocked, report a concrete blocker.

Repository role controls judgment and authority. Work intent controls allowed actions.
When these point in different directions, obey both: for example, `owner` + `review_only` means review with owner-level judgment and pushback, but do not modify code or metadata.
