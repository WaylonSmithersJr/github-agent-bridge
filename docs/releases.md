# Releases

This repository uses `python-semantic-release` from GitHub Actions to create versions automatically from Conventional Commits on `main`.

## What happens on `main`

When commits land on `main`, the `release` workflow:

1. reads commits since the last `vX.Y.Z` tag,
2. decides the next SemVer version,
3. updates `pyproject.toml` (`project.version`),
4. updates `CHANGELOG.md`,
5. commits the release bump,
6. creates a `vX.Y.Z` tag,
7. creates a GitHub Release,
8. builds `sdist`/wheel artifacts and uploads them to the GitHub Release.

No PyPI publish is configured yet.

## Commit convention

Use Conventional Commits:

- `fix: ...` → patch release, for example `0.1.0` → `0.1.1`
- `feat: ...` → minor release, for example `0.1.0` → `0.2.0`
- `feat!: ...` or `BREAKING CHANGE: ...` → major release, for example `0.1.0` → `1.0.0`
- `docs: ...`, `test: ...`, `refactor: ...`, `chore: ...` → no release by default unless marked breaking

Useful examples:

```text
fix: keep packaged prompt resources in wheels
feat: add retry policy for blocked jobs
feat!: change policy action names
```

## Manual run

The workflow can also be triggered manually from GitHub Actions with `workflow_dispatch`. Manual runs still inspect commits and only release when the commit history implies a new version.

## Configuration

Release configuration lives in `pyproject.toml` under `[tool.semantic_release]`.

The workflow lives in `.github/workflows/release.yml` and uses `GITHUB_TOKEN` with `contents: write` and `id-token: write` permissions, as required by `python-semantic-release`.
