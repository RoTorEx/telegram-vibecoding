# Release Contract

Read this file only for version, tag, publishing, or release work.

## Preconditions

- The user explicitly approved the release.
- The project has a real release process and implements `make release` and
  `make release-push`.
- Normal work is already committed and the worktree is clean.
- `CHANGELOG.md` describes all notable unreleased behavior under
  `## [Unreleased]`.

## Invocation contract

For a real release, the agent must start exactly `make release` in an
interactive terminal, wait for its version prompt, and send the exact version
to the running process through standard input.

Do not put the version in the shell command: no pipe or heredoc, environment
assignment, positional argument, or version flag. The stable command lets one
execution approval remain reusable across releases instead of requiring a new
approval for every version.

Automated tests may inject standard input into an isolated release process.
They are verification, not a real release.

## `make release`

The normal release command:

1. Prompts for the exact `MAJOR.MINOR.PATCH` version.
2. Validates the version and refuses an existing `vMAJOR.MINOR.PATCH` tag.
3. Runs `make check`.
4. Updates the project's native version sources and required lock metadata.
5. Moves `CHANGELOG.md` Unreleased entries under
   `## [MAJOR.MINOR.PATCH] - YYYY-MM-DD` and leaves a new empty Unreleased section.
6. Creates one dedicated release commit.
7. Creates an annotated `vMAJOR.MINOR.PATCH` tag.

It does not push, publish, or deploy.

## `make release-push`

This command verifies that the release tag exists, then pushes the current
tracked branch and its tags. It does not force push.

## Publishing

Artifact building, GitHub Releases, package registries, app stores, and deploys
are project-specific. Document and implement only the delivery mechanisms the
project actually uses. Do not add a publishing system merely to satisfy the
kernel.

Before pushing the first tag through a new or materially changed automated
publishing workflow, run the closest practical non-release preflight. Verify
that every configured supported target can resolve or build, expected artifacts
reach the publisher, and the publisher has the required repository context and
permissions. A recent successful tagged run is sufficient only when the
workflow and relevant dependency paths are unchanged. Do not add unsupported
targets merely for this check. After pushing, read back the workflow conclusion
and expected published assets.

## Changelog

Record user-visible behavior, important fixes, migrations, and delivery changes.
Do not use the changelog as a commit log. Do not invent future work.
