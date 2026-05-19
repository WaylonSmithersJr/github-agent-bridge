# CHANGELOG

<!-- version list -->

## v0.8.3 (2026-05-19)

### Bug Fixes

- Make monitor alert wrapper self-contained
  ([`be4ccf1`](https://github.com/pilipilisbot/github-agent-bridge/commit/be4ccf1b932a1131e47741f3a63b42b4ec8a4dc8))


## v0.8.2 (2026-05-19)

### Bug Fixes

- Replace monitor alert shell wrapper
  ([`3883d47`](https://github.com/pilipilisbot/github-agent-bridge/commit/3883d47a62b96c659af9192280b52c99c1e3b2b1))


## v0.8.1 (2026-05-19)

### Bug Fixes

- Add bridge monitor alert command
  ([`ab52e4b`](https://github.com/pilipilisbot/github-agent-bridge/commit/ab52e4b7e0dbfe70fd202dafd8e38f3928112f05))


## v0.8.0 (2026-05-19)

### Features

- Add autoskills project skills
  ([`9ac6068`](https://github.com/pilipilisbot/github-agent-bridge/commit/9ac6068c1fd4216a374059cb70d2212ff93d1e5e))


## v0.7.8 (2026-05-19)

### Bug Fixes

- Handle github bridge event gaps
  ([`4373801`](https://github.com/pilipilisbot/github-agent-bridge/commit/4373801db9646805ee0b4298f53a20a5037b1915))

### Chores

- Remove obsolete reader script
  ([`68423d2`](https://github.com/pilipilisbot/github-agent-bridge/commit/68423d29c64f284a0fa41049a981b5648fc8d442))


## v0.7.7 (2026-05-17)

### Bug Fixes

- Avoid duplicate dispatch on retry
  ([`f028db2`](https://github.com/pilipilisbot/github-agent-bridge/commit/f028db22ffe33b4fa124a0ea69006104b971b2e4))


## v0.7.6 (2026-05-17)

### Bug Fixes

- Do not coalesce into running jobs
  ([`421ee9f`](https://github.com/pilipilisbot/github-agent-bridge/commit/421ee9ff935aa63a34d1d49030dfc538d6ecdd18))


## v0.7.5 (2026-05-17)

### Bug Fixes

- React to coalesced github notifications
  ([`45ebe3c`](https://github.com/pilipilisbot/github-agent-bridge/commit/45ebe3cab131530de4334cf47e341bd75dad5a24))


## v0.7.4 (2026-05-17)

### Bug Fixes

- Reject task requests in feedback learning
  ([`c036ba9`](https://github.com/pilipilisbot/github-agent-bridge/commit/c036ba9725af78cec09d0e17d3cbf3525488f39d))


## v0.7.3 (2026-05-17)

### Bug Fixes

- Inline feedback rules in github task prompts
  ([`a9f7bde`](https://github.com/pilipilisbot/github-agent-bridge/commit/a9f7bdee47739b2a8e338e4415401c9f3c019982))

### Documentation

- Explain feedback learning model selection
  ([`112ade8`](https://github.com/pilipilisbot/github-agent-bridge/commit/112ade8e1ac171865b6b139e8a4c83dc664d9bf3))

- Include feedback learning model in policy example
  ([`a5e19a3`](https://github.com/pilipilisbot/github-agent-bridge/commit/a5e19a3a92183bb117e7e46ae0e376691013a24d))


## v0.7.2 (2026-05-16)

### Bug Fixes

- Make prompt rules overrideable
  ([`5c79175`](https://github.com/pilipilisbot/github-agent-bridge/commit/5c7917570b609d7ac573d40705669ececf5a0f5f))


## v0.7.1 (2026-05-16)

### Bug Fixes

- Move feedback classifier prompt to resource
  ([`b698888`](https://github.com/pilipilisbot/github-agent-bridge/commit/b698888dc02c6ad2015826dbf52fc48e69b51c46))


## v0.7.0 (2026-05-16)

### Features

- Add autonomous feedback learning pass
  ([`8669357`](https://github.com/pilipilisbot/github-agent-bridge/commit/866935700bb5d744d1979a117a8645908107b725))


## v0.6.4 (2026-05-16)

### Bug Fixes

- Remove heuristic feedback synthesis
  ([`bb924f2`](https://github.com/pilipilisbot/github-agent-bridge/commit/bb924f2df9079dfe17e9e1f09c6c1e95f59153f5))


## v0.6.3 (2026-05-16)

### Bug Fixes

- Make feedback learning policy-driven
  ([`c73091a`](https://github.com/pilipilisbot/github-agent-bridge/commit/c73091a247289d26cbe31f99c6a53ebd122e3b98))


## v0.6.2 (2026-05-16)

### Bug Fixes

- Store feedback learning in bridge database
  ([`e3f65aa`](https://github.com/pilipilisbot/github-agent-bridge/commit/e3f65aa30bc7b2e7ee794bc440233c1df6a6f921))


## v0.6.1 (2026-05-16)

### Bug Fixes

- Make feedback learner path configurable
  ([`a45d9d5`](https://github.com/pilipilisbot/github-agent-bridge/commit/a45d9d5e11edda90d354a01eb0e7841b6b95becb))


## v0.6.0 (2026-05-16)

### Bug Fixes

- Allow bot-authored PR review followups to work
  ([`74b764f`](https://github.com/pilipilisbot/github-agent-bridge/commit/74b764f7ca3368c0a4617bbc4213ec31f7470529))

### Features

- Capture feedback learning events
  ([`8dbd055`](https://github.com/pilipilisbot/github-agent-bridge/commit/8dbd0556425f419068c9e5b496fee757ddd8e99c))


## v0.5.8 (2026-05-14)

### Bug Fixes

- Install systemd reader wrapper
  ([`563fb34`](https://github.com/pilipilisbot/github-agent-bridge/commit/563fb341a9f03ea0740e880e780e7d576c932fa3))

### Documentation

- Add bridge installation guide
  ([`5fb3e8a`](https://github.com/pilipilisbot/github-agent-bridge/commit/5fb3e8a784e7557406ed327cc3c5b234c6134641))


## v0.5.7 (2026-05-13)

### Bug Fixes

- Harden github prompts against injection
  ([`f0f4bce`](https://github.com/pilipilisbot/github-agent-bridge/commit/f0f4bce2bfcee2ff3d3aeda9b66a8f1c527b8a96))


## v0.5.6 (2026-05-13)

### Bug Fixes

- Require new value before github comments
  ([`fa3010e`](https://github.com/pilipilisbot/github-agent-bridge/commit/fa3010eb778f861d6d8573f8f5a1e679aa582a08))


## v0.5.5 (2026-05-13)

### Bug Fixes

- Skip non-actionable copilot reviews
  ([`214fb40`](https://github.com/pilipilisbot/github-agent-bridge/commit/214fb40c582a6352fcb04e77aa4034138c2c2e9d))


## v0.5.4 (2026-05-13)

### Bug Fixes

- Skip comments not addressed to bot
  ([`3e18d92`](https://github.com/pilipilisbot/github-agent-bridge/commit/3e18d920306e67c1cdafd28c0a6bbf9475efa8ac))


## v0.5.3 (2026-05-13)

### Bug Fixes

- Upgrade assigned PR comments to work allowed
  ([`d64580a`](https://github.com/pilipilisbot/github-agent-bridge/commit/d64580aeea38a768612ee5cb9da3e639978fdca4))


## v0.5.2 (2026-05-13)

### Bug Fixes

- Allow assigned PR work to mutate
  ([`30265ed`](https://github.com/pilipilisbot/github-agent-bridge/commit/30265ed6c238dd000919160316926045a16be240))


## v0.5.1 (2026-05-13)

### Bug Fixes

- Keep PR review followups read-only
  ([`a41458b`](https://github.com/pilipilisbot/github-agent-bridge/commit/a41458bf4ce01d43307db5a79fd7cd2d12d0931b))


## v0.5.0 (2026-05-13)

### Features

- Submit formal reviews for review requests
  ([`5c98b3c`](https://github.com/pilipilisbot/github-agent-bridge/commit/5c98b3c9ae4e58bb82c786c1ef2042169103ef85))


## v0.4.0 (2026-05-12)

### Features

- Dispatch post-merge workspace cleanup
  ([`f630f25`](https://github.com/pilipilisbot/github-agent-bridge/commit/f630f250b122ed7ba168efbe4f19610acec49b9f))


## v0.3.0 (2026-05-12)

### Documentation

- Clarify role and intent interaction
  ([`517edbb`](https://github.com/pilipilisbot/github-agent-bridge/commit/517edbb14ea6beaa9332c697aaedf90146c19ace))

- Improve documentation design
  ([`a7464af`](https://github.com/pilipilisbot/github-agent-bridge/commit/a7464aff3a62d5e74cf72bdae8ee6f76702fd124))

### Features

- Support policy prompt overrides
  ([`a61b9d5`](https://github.com/pilipilisbot/github-agent-bridge/commit/a61b9d55bb6fa76c7fce3fa51793d72f355d272e))


## v0.2.0 (2026-05-12)

### Chores

- Configure semantic releases
  ([`74f950c`](https://github.com/pilipilisbot/github-agent-bridge/commit/74f950c7c6581906613ddfb5cb65603edc9529d7))

### Features

- Add repository roles to policy
  ([`f17e417`](https://github.com/pilipilisbot/github-agent-bridge/commit/f17e417c230b0eafb0d938f7bb88ec6d0bcebb56))


## v0.1.0 (2026-05-12)
