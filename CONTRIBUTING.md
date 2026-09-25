# Contributing to the HauntedMC release CLI

Thanks for helping maintain the release tooling used across HauntedMC projects.

## Development setup

Use Python 3.11 or newer, Git, and the GitHub CLI. The extension uses only the
Python standard library. Maven is needed only when testing verification against
a consuming repository.

```sh
git clone https://github.com/HauntedMC/gh-haunted-release.git
cd gh-haunted-release
python3 -m unittest discover -s tests -v
./gh-haunted-release --version
```

The shared commands live in `release_cli/`. Each consuming project owns its
version-file edits in `tools/release/prepare-version.sh` and its configuration in
`tools/release/project.toml`. See the [new repository guide](docs/new-repository.md)
before changing that contract.

## Pull requests

Branch from `main`, keep the change focused, and fill out the pull request
template. Add a regression test for behavior changes. Test version preparation
in a disposable Git worktree when changing its Git or adapter behavior. Document
changes to commands or configuration, and explain any compatibility impact on
consuming repositories. If the `project.toml` contract changes incompatibly,
update the tool version and the consuming repositories together.

Report vulnerabilities privately using [SECURITY.md](SECURITY.md), rather than
opening a public issue.
