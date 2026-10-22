# Contributing

Git workflow and commit rules for this repository. They apply to humans and AI agents alike.

## Branches

- **Never commit directly to `main`.** All changes land through a pull request.
- Create a short-lived branch from an up-to-date `main`:
  - `feature/<short-description>` for new functionality
  - `fix/<short-description>` for bug fixes
  - `docs/…`, `chore/…`, `refactor/…`, `test/…` for the corresponding changes
- Keep one topic per branch and per pull request.

## Keeping history linear

- **Use rebase, not merge.** Update your branch with `git pull --rebase` or `git rebase origin/main`. Do not create merge commits in feature branches.
- Pull requests are integrated into `main` with **fast-forward** or **squash** only (no merge commits).
- Clean up your branch before opening a PR (`git rebase -i`): squash fixups, reword unclear messages.

## Force-push

- **Never force-push to `main`.**
- On your own branches use only `git push --force-with-lease` (never plain `--force`), and only after a rebase.

## Commits

- **Atomic commits:** one logical change per commit. The project should work (and tests pass) at every commit.
- Follow [Conventional Commits](https://www.conventionalcommits.org/):

  ```
  <type>(<optional scope>): <subject>

  <optional body: what and why, wrapped at ~72 chars>
  ```

  Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- Write messages **in English**, in the **imperative mood** ("add fetcher", not "added" / "adds").
- Subject line: **72 characters max**, no trailing period.
- Explain *why* in the body when the reason is not obvious from the diff.

Examples:

```
feat(fetcher): add concurrent RSS ingestion
fix(scheduler): avoid duplicate delivery within the same minute
docs: add commit guidelines
```

## Before you commit / push

- Run the test suite and make sure it passes:

  ```bash
  .venv/bin/python -m pytest
  ```
- Review your diff (`git diff --staged`) and make sure it contains only what belongs to the commit.

## Never commit

- Secrets: `.env`, API keys, bot tokens, credentials. Only `.env.example` with placeholder values is tracked.
- Database files: `*.db`, `*.db-wal`, `*.db-shm` and the `data/` directory.
- Virtual environments, caches and other generated files (`.venv/`, `__pycache__/`, `.pytest_cache/`).

If a secret is committed by accident, treat it as leaked: revoke and rotate it immediately, then remove it from history.
