# Add a HauntedMC repository to the release flow

1. Copy the `tools/release/` layout from an existing repository. Keep only one project-specific adapter, `prepare-version.sh`, and the small `project.toml` configuration. The adapter receives `major`, `minor`, or `patch` (or an exact version for Platform). Multi-component projects receive the component name first. It must update every version-bearing file and fail if its expected old version or metadata is missing.
2. Set `project.repository`, `project.name`, `project.mode`, and `project.tool_version` in `project.toml`. Define each independently released component's POM and tag prefix. Supply a `verify` command; set `verify_before_pr = true` only when GitHub Actions are paused.
3. Add the `tools/release/update-version` wrapper, CI ShellCheck and `--dry-run` smoke checks, and a release workflow that calls `gh haunted-release gate` before publication and `gh haunted-release verify-published` before tagging. Pin the extension to a reviewed commit SHA in workflows.
4. Test a patch bump in a disposable worktree. Check the changed file list and run Maven verification. Confirm the release gate and published-coordinate list before opening the tooling PR.
5. Add the repository and its dependency edges to HauntedPlatform's `scripts/update-consumers.py` only if it consumes or produces internal packages. Extend the reconciler tests for the new edge. Keep PRs reviewed and merge them before any version bump relies on the new tooling.

For a normal version PR, run `./tools/release/update-version patch --pr` from clean, current `main`. `--dry-run` prints the target without edits; omitting `--pr` only prepares a local diff. The command never merges, publishes, or tags.
