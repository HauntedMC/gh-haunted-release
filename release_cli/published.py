"""Resolve deployed Maven coordinates from a fresh local repository."""

import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import os
from pathlib import Path

NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def coordinates(root, config, component_name=None):
    components = config["components"]
    if component_name is not None:
        if component_name not in components:
            raise ValueError(f"Unknown component {component_name!r}")
        paths = [root / components[component_name]["pom"]]
    else:
        if len(components) != 1:
            raise ValueError("Choose --component for this repository")
        root_pom = root / next(iter(components.values()))["pom"]
        paths = [root_pom]
        parent = ET.parse(root_pom).getroot()
        paths += [root / name.text / "pom.xml" for name in parent.findall("m:modules/m:module", NS)]
    result = []
    excluded = set(config["project"].get("exclude_artifacts", []))
    for path in paths:
        pom = ET.parse(path).getroot()
        artifact = pom.findtext("m:artifactId", namespaces=NS)
        if artifact in excluded or artifact.endswith("-platform-acceptance"):
            continue
        group = pom.findtext("m:groupId", namespaces=NS) or pom.findtext(
            "m:parent/m:groupId", namespaces=NS
        )
        packaging = pom.findtext("m:packaging", default="jar", namespaces=NS)
        result.append((group, artifact, packaging))
    if not result:
        raise ValueError("No release coordinates found")
    return result


def resolution_commands(root, config, args, temporary):
    if not args.version or len(args.version.split(".")) != 3 or not all(
        part.isdigit() for part in args.version.split(".")
    ):
        raise ValueError("Expected a semantic release version")
    artifacts = [
        f"{group}:{artifact}:{args.version}:{packaging}"
        for group, artifact, packaging in coordinates(root, config, args.component)
    ]
    repo_name = config["project"]["repository"].split("/", 1)[1]
    maven = "./mvnw" if (root / "mvnw").is_file() else "mvn"
    location = Path(temporary)
    local_repo = location / "repository"
    consumer = location / "pom.xml"
    consumer.write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        '<modelVersion>4.0.0</modelVersion>'
        '<groupId>nl.hauntedmc.verification</groupId>'
        '<artifactId>published-resolution</artifactId><version>1</version>'
        '</project>'
    )
    for artifact in artifacts:
        yield artifact, [
            maven, "-B", "-ntp", "-U", "-f", str(consumer),
            f"-Dmaven.repo.local={local_repo}",
            "org.apache.maven.plugins:maven-dependency-plugin:3.11.0:get",
            f"-Dartifact={artifact}", "-Dtransitive=false",
            f"-DremoteRepositories=github::default::https://maven.pkg.github.com/HauntedMC/{repo_name}",
        ]


def verify_published(root, config, args):
    with tempfile.TemporaryDirectory(prefix="haunted-published-m2-") as temporary:
        for artifact, command in resolution_commands(root, config, args, temporary):
            if args.list:
                print(artifact)
                continue
            for attempt in range(6):
                result = subprocess.run(command, cwd=root, check=False)
                if result.returncode == 0:
                    break
                if attempt == 5:
                    raise RuntimeError(f"Published artifact could not be resolved: {artifact}")
                time.sleep(10)
            print(f"Resolved {artifact}", flush=True)


def published_state(root, config, args):
    """Classify a release before deploy so reruns never blindly redeploy it."""
    present = []
    missing = []
    with tempfile.TemporaryDirectory(prefix="haunted-preflight-m2-") as temporary:
        for artifact, command in resolution_commands(root, config, args, temporary):
            result = subprocess.run(command, cwd=root, check=False,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (present if result.returncode == 0 else missing).append(artifact)
    state = "complete" if not missing else "none" if not present else "partial"
    print(f"{state}: {len(present)} present, {len(missing)} missing", flush=True)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"state={state}\n")
    if state == "partial":
        raise RuntimeError("Partial Maven publication; inspect missing coordinates before retrying: "
                           + ", ".join(missing))
