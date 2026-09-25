import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from release_cli.cli import bump, publish_pr_command, version
from release_cli.published import coordinates

CLI = Path(__file__).resolve().parents[1] / "gh-haunted-release"


class VersionToolTest(unittest.TestCase):
    def test_version_calculation(self):
        self.assertEqual(bump("2.4.9", "patch", "bump"), "2.4.10")
        self.assertEqual(bump("2.4.9", "minor", "bump"), "2.5.0")
        self.assertEqual(bump("2.4.9", "major", "bump"), "3.0.0")
        self.assertEqual(bump("2.4.9", "2.5.0", "exact"), "2.5.0")
        with self.assertRaises(ValueError):
            bump("2.4.9", "2.4.8", "exact")

    def test_pom_version_supports_revision_and_explicit_version(self):
        prefix = '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        self.assertEqual(version(prefix + '<properties><revision>1.2.3</revision></properties></project>'), "1.2.3")
        self.assertEqual(version(prefix + '<version>2.0.1</version></project>'), "2.0.1")

    def test_prepare_only_and_dry_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-qb", "main", root], check=True)
            subprocess.run(["git", "-C", root, "config", "user.name", "test"], check=True)
            subprocess.run(["git", "-C", root, "config", "user.email", "test@example.invalid"], check=True)
            folder = root / "tools/release"
            folder.mkdir(parents=True)
            (folder / "project.toml").write_text(
                '[project]\nname="Example"\nrepository="HauntedMC/Example"\n'
                'tool_version="1.0.1"\nprepare="tools/release/prepare-version.sh"\n'
                '[components.default]\npom="pom.xml"\ntag_prefix="v"\n'
            )
            adapter = folder / "prepare-version.sh"
            adapter.write_text('#!/bin/sh\npython3 -c "from pathlib import Path; p=Path(\'pom.xml\'); p.write_text(p.read_text().replace(\'<revision>1.2.3</revision>\', \'<revision>1.2.4</revision>\'))"\n')
            adapter.chmod(0o755)
            pom = root / "pom.xml"
            pom.write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                '<properties><revision>1.2.3</revision></properties></project>'
            )
            subprocess.run(["git", "-C", root, "add", "-A"], check=True)
            subprocess.run(["git", "-C", root, "commit", "-qm", "initial"], check=True)
            dry = subprocess.run([CLI, "version", "patch", "--dry-run"], cwd=root,
                                 check=True, capture_output=True, text=True)
            self.assertIn("1.2.3 → 1.2.4", dry.stdout)
            self.assertIn("1.2.3", pom.read_text())
            subprocess.run([CLI, "version", "patch"], cwd=root, check=True,
                           capture_output=True, text=True)
            self.assertIn("1.2.4", pom.read_text())

    def test_release_gate_writes_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-qb", "main", root], check=True)
            folder = root / "tools/release"
            folder.mkdir(parents=True)
            (folder / "project.toml").write_text(
                '[project]\nname="Example"\nrepository="HauntedMC/Example"\n'
                'tool_version="1.0.1"\n'
                '[components.default]\npom="pom.xml"\ntag_prefix="v"\n'
            )
            (root / "pom.xml").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                '<properties><revision>1.2.4</revision></properties></project>'
            )
            subprocess.run(["git", "-C", root, "config", "user.name", "test"], check=True)
            subprocess.run(["git", "-C", root, "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", root, "add", "-A"], check=True)
            subprocess.run(["git", "-C", root, "commit", "-qm", "initial"], check=True)
            output = root / "outputs"
            env = dict(os.environ, GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_OUTPUT=str(output))
            subprocess.run([CLI, "gate"], cwd=root, env=env, check=True,
                           capture_output=True, text=True)
            self.assertIn("publish=true", output.read_text())
            subprocess.run(["git", "-C", root, "tag", "v1.2.4"], check=True)
            output.write_text("")
            subprocess.run([CLI, "gate"], cwd=root, env=env, check=True,
                           capture_output=True, text=True)
            self.assertIn("publish=false", output.read_text())

    def test_pr_mode_verifies_then_pushes_review_branch(self):
        with tempfile.TemporaryDirectory() as temporary:
            place = Path(temporary)
            bare = place / "remote.git"
            root = place / "work"
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
            subprocess.run(["git", "init", "-qb", "main", root], check=True)
            subprocess.run(["git", "-C", root, "config", "user.name", "test"], check=True)
            subprocess.run(["git", "-C", root, "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", root, "remote", "add", "origin", bare], check=True)
            folder = root / "tools/release"
            folder.mkdir(parents=True)
            (folder / "project.toml").write_text(
                '[project]\nname="Example"\nrepository="HauntedMC/Example"\n'
                'tool_version="1.0.1"\nprepare="tools/release/prepare-version.sh"\n'
                'verify_before_pr=true\nverify=["/bin/true"]\n'
                '[components.default]\npom="pom.xml"\ntag_prefix="v"\n'
            )
            adapter = folder / "prepare-version.sh"
            adapter.write_text('#!/bin/sh\npython3 -c "from pathlib import Path; p=Path(\'pom.xml\'); p.write_text(p.read_text().replace(\'<revision>1.2.3</revision>\', \'<revision>1.2.4</revision>\'))"\n')
            adapter.chmod(0o755)
            (root / "pom.xml").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                '<properties><revision>1.2.3</revision></properties></project>'
            )
            subprocess.run(["git", "-C", root, "add", "-A"], check=True)
            subprocess.run(["git", "-C", root, "commit", "-qm", "initial"], check=True)
            subprocess.run(["git", "-C", root, "push", "-q", "-u", "origin", "main"], check=True)
            fake = place / "bin"
            fake.mkdir()
            gh = fake / "gh"
            gh.write_text(
                '#!/bin/sh\ncase "$1 $2" in\n'
                '  "pr list") echo "[]" ;;\n'
                '  "pr create") echo "https://github.com/HauntedMC/Example/pull/1" ;;\n'
                '  *) exit 2 ;;\nesac\n'
            )
            gh.chmod(0o755)
            env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ["PATH"])
            result = subprocess.run([CLI, "version", "patch", "--pr"], cwd=root,
                                    env=env, check=True, capture_output=True, text=True)
            self.assertIn("https://github.com/HauntedMC/Example/pull/1", result.stdout)
            self.assertEqual(subprocess.check_output(
                ["git", "-C", root, "branch", "--show-current"], text=True
            ).strip(), "release/v1.2.4")
            self.assertIn("refs/heads/release/v1.2.4", subprocess.check_output(
                ["git", "--git-dir", bare, "show-ref"], text=True
            ))

    def test_coordinate_listing_excludes_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("pom.xml").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                '<groupId>nl.hauntedmc.example</groupId><artifactId>example</artifactId>'
                '<modules><module>example-platform-acceptance</module></modules></project>'
            )
            module = root / "example-platform-acceptance"
            module.mkdir()
            module.joinpath("pom.xml").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                '<groupId>nl.hauntedmc.example</groupId>'
                '<artifactId>example-platform-acceptance</artifactId></project>'
            )
            self.assertEqual(coordinates(root, {"components": {"default": {"pom": "pom.xml"}},
                                                "project": {}}, None),
                             [("nl.hauntedmc.example", "example", "jar")])

    def test_refresh_existing_pr_uses_rest_body_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            body_file = root / "body.md"
            body_file.write_text("Updated dependency versions.\n\nReady for review.\n")
            calls = []

            def fake_command(*args, **kwargs):
                calls.append(args)
                if args[:4] == ("gh", "api", "-X", "PATCH"):
                    self.assertEqual(json.loads(Path(args[-1]).read_text()),
                                     {"body": body_file.read_text()})
                return ""

            args = SimpleNamespace(branch="automation/internal-dependencies",
                                   title="Update dependencies", body_file=str(body_file))
            config = {"project": {"repository": "HauntedMC/Example"}}
            prior = {"number": 7, "url": "https://github.com/HauntedMC/Example/pull/7",
                     "isDraft": False}
            with patch("release_cli.cli.root_path", return_value=root), \
                 patch("release_cli.cli.load_config", return_value=config), \
                 patch("release_cli.cli.remote_branch", return_value=False), \
                 patch("release_cli.cli.existing_pr", return_value=prior), \
                 patch("release_cli.cli.command", side_effect=fake_command):
                publish_pr_command(args)
            self.assertEqual(calls[-1][:6], ("gh", "api", "-X", "PATCH",
                                              "repos/HauntedMC/Example/pulls/7", "--input"))


if __name__ == "__main__":
    unittest.main()
