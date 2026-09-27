# ADR-011: Bootstrap `main` once, then feature branches and PRs

**Status**: Accepted (M1, chosen by Amit) · **Date**: 2026-09-27

## Context
Amit's standing rule is to never commit to `main`/`master`. The target repo (`amit-gautam-09/Veera`) was empty,
so no base branch existed for pull requests.

## Decision
One bootstrap commit on `main` containing only `.gitignore` and a stub README (`chore: initialize repository`).
All further work goes on feature branches (`docs/m1-foundation`, `feat/m2-skeleton`, …), pushed with PRs that
Amit merges. Conventional Commits. Before any push, confirm `gh auth status --active` shows `amit-gautam-09`.

## Consequences
- `main` only moves through reviewed merges.
- Milestone branches stack when PRs are not merged yet; each PR description lists its base.
