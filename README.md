# HauntedMC release CLI

This public [GitHub CLI extension](https://cli.github.com/manual/gh_extension) provides the common version-PR, release-gate, and published-artifact checks used by HauntedMC projects. Project-specific file edits stay in each project's `tools/release/prepare-version.sh`.

Install the version pinned by a project's `tools/release/project.toml`:

```sh
gh extension install HauntedMC/gh-haunted-release --pin v1.0.3
```

If an older pinned extension is installed, replace it with
`gh extension remove haunted-release` followed by the install command above.
Run `gh haunted-release --version` to confirm the installed version.

From a clean, current `main` worktree, run `./tools/release/update-version patch --pr`
to prepare, push, and open a version PR. The `--pr` path uses a temporary worktree,
so failure leaves your checkout on `main`; rerunning safely checks an existing branch
and repeats mandatory local verification. Omit `--pr` to prepare an editable local
diff, or use `--dry-run` to print the next version. Theme adds
`--component palette` or `--component adapter`; HauntedPlatform takes an exact
semantic version.

`gh haunted-release verify-pr NUMBER` locally verifies a PR at its exact head commit.
For ProxyFeatures and ServerFeatures, it posts the required
`hauntedmc/local-maven` status and marks a passing draft ready. A new commit must be
verified again. The `gate`, `published-state`, `verify-published`, and
`publish-pr` commands are used by repository workflows and HauntedPlatform's
dependency reconciler.

The release workflow checks every Maven coordinate before deployment. If none exist,
it builds and deploys; if all exist, it verifies them and completes the tag without
redeploying. If only some exist, it stops: inspect the reported missing coordinates
and correct the partial publication before rerunning `workflow_dispatch`.

The tool never merges a PR, deploys artifacts, or creates a release tag.

See [the new repository guide](docs/new-repository.md) for the adapter contract and rollout checks.

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Report
security issues privately through [SECURITY.md](SECURITY.md). The project uses
the [AGPL-3.0 license](LICENSE) and follows the [Code of Conduct](CODE_OF_CONDUCT.md).
