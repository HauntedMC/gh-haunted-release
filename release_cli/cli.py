"""Project-local release preparation with shared Git and GitHub operations."""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from .published import verify_published

NS = {"m": "http://maven.apache.org/POM/4.0.0"}
SEMVER = re.compile(r"\d+\.\d+\.\d+")
TOOL_VERSION = "1.0.0"


def command(*args, cwd=None, capture=True, env=None):
    result = subprocess.run(
        args, cwd=cwd, env=env, text=True, capture_output=capture, check=False
    )
    if result.returncode:
        detail = result.stderr.strip() if capture else "see command output"
        raise RuntimeError(f"{' '.join(map(str, args))} failed: {detail}")
    return result.stdout.strip() if capture else ""


def root_path():
    return Path(command("git", "rev-parse", "--show-toplevel"))


def load_config(root):
    path = root / "tools/release/project.toml"
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    project = config["project"]
    if project.get("tool_version") != TOOL_VERSION:
        raise ValueError(
            f"Project requires release tool {project.get('tool_version')}; installed {TOOL_VERSION}"
        )
    if not project.get("repository", "").startswith("HauntedMC/"):
        raise ValueError("project.repository must be a HauntedMC repository")
    if not config.get("components"):
        raise ValueError("project.toml must declare at least one component")
    return config


def component(config, name):
    components = config["components"]
    if name is None:
        if len(components) != 1:
            raise ValueError("Choose --component for this repository")
        name = next(iter(components))
    if name not in components:
        raise ValueError(f"Unknown component {name!r}; choose from {', '.join(components)}")
    return name, components[name]


def version(xml):
    pom = ET.fromstring(xml)
    value = pom.findtext("m:properties/m:revision", namespaces=NS)
    if value is None:
        value = pom.findtext("m:version", namespaces=NS)
    if not value or not SEMVER.fullmatch(value):
        raise ValueError(f"Expected a semantic release version in POM, got {value!r}")
    return value


def bump(current, requested, mode):
    if mode == "exact":
        if not SEMVER.fullmatch(requested):
            raise ValueError("This project requires an explicit X.Y.Z version")
        target = requested
    else:
        if requested not in {"major", "minor", "patch"}:
            raise ValueError("Choose major, minor, or patch")
        major, minor, patch = map(int, current.split("."))
        if requested == "major":
            target = f"{major + 1}.0.0"
        elif requested == "minor":
            target = f"{major}.{minor + 1}.0"
        else:
            target = f"{major}.{minor}.{patch + 1}"
    if tuple(map(int, target.split("."))) <= tuple(map(int, current.split("."))):
        raise ValueError(f"Version must advance beyond {current}")
    return target


def clean_tree(root):
    if command("git", "status", "--porcelain", cwd=root):
        raise ValueError("Working tree must be clean before preparing a version")


def existing_pr(root, repository, branch):
    import json

    result = command(
        "gh", "pr", "list", "-R", repository, "--state", "open",
        "--head", branch, "--json", "number,url,isDraft", cwd=root,
    )
    pulls = json.loads(result)
    return pulls[0] if pulls else None


def remote_branch(root, branch):
    return bool(command("git", "ls-remote", "--heads", "origin", branch, cwd=root))


def pr_title(config, target, name):
    label = config["project"]["name"]
    if name != "default":
        label += f" {name}"
    return f"chore: prepare {label} {target}"


def pr_body(config, old, target, tag, validation):
    label = config["project"]["name"]
    return (
        f"Prepare {label} {old} → {target} ({tag}) for review. "
        "The repository's version adapter updates and checks its project-specific metadata.\n\n"
        f"Validation: {validation}.\n\n"
        "Merging follows the repository's release policy. This PR does not publish or tag a release.\n"
    )


def create_pr(root, repository, branch, title, body, draft=False):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md") as stream:
        stream.write(body)
        stream.flush()
        args = [
            "gh", "pr", "create", "-R", repository, "--base", "main", "--head", branch,
            "--title", title, "--body-file", stream.name,
        ]
        if draft:
            args.append("--draft")
        return command(*args, cwd=root)


def version_command(args):
    root = root_path()
    config = load_config(root)
    name, part = component(config, args.component)
    pom = part["pom"]
    current = version((root / pom).read_text())
    target = bump(current, args.version, config["project"].get("mode", "bump"))
    tag = part.get("tag_prefix", "v") + target
    branch = "release/" + ("" if name == "default" else name + "-") + tag
    print(f"{config['project']['name']}: {current} → {target} ({tag})", flush=True)
    if args.dry_run:
        return
    clean_tree(root)
    if args.pr:
        command("git", "fetch", "origin", "main", "--tags", cwd=root, capture=False)
        if command("git", "branch", "--show-current", cwd=root) != "main":
            raise ValueError("--pr must start on main")
        if command("git", "rev-parse", "HEAD", cwd=root) != command(
            "git", "rev-parse", "origin/main", cwd=root
        ):
            raise ValueError("main must match origin/main before opening a version PR")
    if subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=root
    ).returncode == 0:
        raise ValueError(f"Release tag {tag} already exists")
    if args.pr and command("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", cwd=root):
        raise ValueError(f"Remote release tag {tag} already exists")
    repository = config["project"]["repository"]
    if args.pr:
        prior = existing_pr(root, repository, branch)
        if prior:
            print(prior["url"])
            return
        if remote_branch(root, branch):
            command("git", "fetch", "origin", branch, cwd=root, capture=False)
            remote_xml = command("git", "show", f"FETCH_HEAD:{pom}", cwd=root)
            if version(remote_xml) != target:
                raise ValueError(f"Remote branch {branch} has a different version")
            validation = "the existing prepared branch; check its previous validation"
            print(create_pr(root, repository, branch, pr_title(config, target, name),
                            pr_body(config, current, target, tag, validation)))
            return
        command("git", "switch", "-c", branch, cwd=root, capture=False)
    prepare = root / config["project"].get("prepare", "tools/release/prepare-version.sh")
    prepare_args = [str(prepare)]
    if name != "default":
        prepare_args.append(name)
    prepare_args.append(args.version)
    command(*prepare_args, cwd=root, capture=False)
    actual = version((root / pom).read_text())
    if actual != target:
        raise ValueError(f"Adapter produced {actual}, expected {target}")
    command("git", "diff", "--check", cwd=root)
    changed = command("git", "diff", "--name-only", "-z", cwd=root).split("\0")
    changed = [path for path in changed if path]
    if not changed:
        raise ValueError("Version adapter did not change tracked files")
    untracked = command("git", "ls-files", "--others", "--exclude-standard", cwd=root)
    if untracked:
        raise ValueError(f"Version adapter created unexpected untracked files: {untracked}")
    if not args.pr:
        print("Version files prepared for review.")
        return
    verify = config["project"].get("verify", [])
    mandatory = config["project"].get("verify_before_pr", False)
    validation = "repository PR CI"
    if mandatory or args.verify:
        if not verify:
            raise ValueError("Project has no local verification command")
        command(*verify, cwd=root, capture=False)
        validation = f"`{' '.join(verify)}` passed locally on this branch"
    command("git", "add", "--", *changed, cwd=root, capture=False)
    command("git", "commit", "-m", pr_title(config, target, name), cwd=root, capture=False)
    command("git", "push", "-u", "origin", branch, cwd=root, capture=False)
    print(create_pr(root, repository, branch, pr_title(config, target, name),
                    pr_body(config, current, target, tag, validation)))


def gate_command(args):
    root = root_path()
    config = load_config(root)
    _, part = component(config, args.component)
    pom = part["pom"]
    current = version((root / pom).read_text())
    tag = part.get("tag_prefix", "v") + current
    before = os.environ.get("GITHUB_EVENT_BEFORE", "")
    previous = None
    if before and before != "0" * 40:
        old = subprocess.run(
            ["git", "show", f"{before}:{pom}"], cwd=root, text=True, capture_output=True
        )
        if old.returncode == 0:
            previous = version(old.stdout)
    exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=root
    ).returncode == 0
    publish = not exists and (
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" or previous != current
    )
    print(f"Current: {current}; previous: {previous}; tag: {tag}; publish: {publish}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"version={current}\ntag={tag}\npublish={str(publish).lower()}\n")


def publish_pr_command(args):
    root = root_path()
    config = load_config(root)
    repository = config["project"]["repository"]
    if not re.fullmatch(r"automation/internal-[a-z-]+", args.branch):
        raise ValueError("publish-pr only manages HauntedMC automation branches")
    if remote_branch(root, args.branch):
        command("git", "fetch", "origin",
                f"refs/heads/{args.branch}:refs/remotes/origin/{args.branch}",
                cwd=root, capture=False)
        same = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", f"origin/{args.branch}"], cwd=root
        )
        if same.returncode == 0:
            prior = existing_pr(root, repository, args.branch)
            if prior:
                print(prior["url"])
                return
    command("git", "push", "--force-with-lease", "origin", f"HEAD:refs/heads/{args.branch}",
            cwd=root, capture=False)
    prior = existing_pr(root, repository, args.branch)
    body = Path(args.body_file).read_text()
    if prior:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".md") as stream:
            stream.write(body)
            stream.flush()
            command("gh", "pr", "edit", str(prior["number"]), "-R", repository,
                    "--body-file", stream.name, cwd=root, capture=False)
        if config["project"].get("verify_before_pr", False) and not prior["isDraft"]:
            command("gh", "pr", "ready", str(prior["number"]), "-R", repository,
                    "--undo", cwd=root, capture=False)
        print(prior["url"])
    else:
        print(create_pr(root, repository, args.branch, args.title, body,
                        draft=config["project"].get("verify_before_pr", False)))


def verify_pr_command(args):
    import json

    root = root_path()
    config = load_config(root)
    repository = config["project"]["repository"]
    verify = config["project"].get("verify", [])
    if not verify:
        raise ValueError("Project has no local verification command")
    clean_tree(root)

    def pull():
        return json.loads(command(
            "gh", "pr", "view", str(args.number), "-R", repository,
            "--json", "headRefOid,isDraft,state", cwd=root
        ))

    initial = pull()
    if initial["state"] != "OPEN":
        raise ValueError("PR is not open")
    sha = initial["headRefOid"]
    command("git", "fetch", "origin", f"pull/{args.number}/head", cwd=root, capture=False)
    if command("git", "rev-parse", "FETCH_HEAD", cwd=root) != sha:
        raise ValueError("Fetched PR head differs from the GitHub PR head")
    with tempfile.TemporaryDirectory(prefix="haunted-verify-pr-") as temporary:
        work = Path(temporary) / "repo"
        command("git", "worktree", "add", "--detach", str(work), sha,
                cwd=root, capture=False)
        try:
            command(*verify, cwd=work, capture=False)
        finally:
            command("git", "worktree", "remove", "--force", str(work),
                    cwd=root, capture=False)
    if pull()["headRefOid"] != sha:
        raise ValueError("PR head changed during verification; run it again")
    body = f"Local Maven verification passed for `{sha}`: `{' '.join(verify)}`."
    command("gh", "pr", "comment", str(args.number), "-R", repository,
            "--body", body, cwd=root, capture=False)
    if initial["isDraft"]:
        command("gh", "pr", "ready", str(args.number), "-R", repository,
                cwd=root, capture=False)
    print(body)


def main():
    parser = argparse.ArgumentParser(prog="gh haunted-release")
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    ver = sub.add_parser("version", help="Prepare a reviewed version update")
    ver.add_argument("version", help="major, minor, patch, or an explicit Platform version")
    ver.add_argument("--component")
    ver.add_argument("--dry-run", action="store_true")
    ver.add_argument("--pr", action="store_true", help="Commit, push, and open a PR")
    ver.add_argument("--verify", action="store_true", help="Run local Maven before opening a PR")
    ver.set_defaults(func=version_command)
    gate = sub.add_parser("gate", help="Set release workflow outputs")
    gate.add_argument("--component")
    gate.set_defaults(func=gate_command)
    published = sub.add_parser("verify-published", help="Resolve all published coordinates")
    published.add_argument("version")
    published.add_argument("--component")
    published.add_argument("--list", action="store_true")
    published.set_defaults(func=lambda args: verify_published(root_path(), load_config(root_path()), args))
    publish = sub.add_parser("publish-pr", help="Open or refresh an automation PR")
    publish.add_argument("--branch", required=True)
    publish.add_argument("--title", required=True)
    publish.add_argument("--body-file", required=True)
    publish.set_defaults(func=publish_pr_command)
    verify = sub.add_parser("verify-pr", help="Locally verify a PR head and mark it ready")
    verify.add_argument("number", type=int)
    verify.set_defaults(func=verify_pr_command)
    args = parser.parse_args()
    try:
        args.func(args)
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print(f"gh haunted-release: {error}", file=sys.stderr)
        raise SystemExit(1) from error
