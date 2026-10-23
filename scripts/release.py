#!/usr/bin/env python3
"""Project-owned interactive release transaction and exact atomic push."""

import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def version_tuple(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Version must use MAJOR.MINOR.PATCH without a prefix.")
    return tuple(map(int, value.split(".")))


def release_changelog(text: str, version: str) -> str:
    marker = "## [Unreleased]"
    if text.count(marker) != 1:
        raise ValueError("Changelog must contain exactly one Unreleased section.")
    start = text.index(marker) + len(marker)
    end = text.find("\n## [", start)
    if end == -1:
        end = len(text)
    entries = text[start:end].strip()
    if not entries:
        raise ValueError("Unreleased changelog is empty.")
    today = datetime.now(ZoneInfo("Europe/Warsaw")).date().isoformat()
    return (
        text[:start].rstrip()
        + f"\n\n## [{version}] - {today}\n\n"
        + entries
        + "\n"
        + ("\n" + text[end:].lstrip() if text[end:].strip() else "")
    )


def clean_main() -> None:
    if run("git", "branch", "--show-current") != "main":
        raise ValueError("Use main for releases.")
    if run("git", "status", "--porcelain"):
        raise ValueError("Commit normal work before release; worktree must be clean.")


def version_file() -> Path:
    config = tomllib.loads(Path("pyproject.toml").read_text())
    return Path(config["tool"]["hatch"]["version"]["path"])


def current_version() -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', version_file().read_text(), re.MULTILINE)
    if match is None:
        raise ValueError("Canonical package version is missing.")
    version_tuple(match[1])
    return match[1]


def prepare() -> None:
    clean_main()
    current = current_version()
    target = input("Release version (MAJOR.MINOR.PATCH): ").strip()
    if version_tuple(target) <= version_tuple(current):
        raise ValueError("Release version must increase.")
    tag = f"v{target}"
    if (
        subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/tags/{tag}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        raise ValueError(f"Tag already exists: {tag}")
    changelog = release_changelog(Path("CHANGELOG.md").read_text(), target)
    subprocess.run(["make", "check"], check=True)
    clean_main()
    paths = [version_file(), Path("CHANGELOG.md"), Path("uv.lock")]
    originals = {p: p.read_bytes() for p in paths}
    try:
        version_file().write_text(
            version_file().read_text().replace(f'__version__ = "{current}"', f'__version__ = "{target}"', 1)
        )
        Path("CHANGELOG.md").write_text(changelog)
        subprocess.run(["uv", "lock", "--offline"], check=True)
        actual = run("uv", "run", "--frozen", "telegram-vibecoding", "--version")
        if actual != target:
            raise ValueError("Installed CLI version does not match the release.")
    except BaseException:
        for path, content in originals.items():
            path.write_bytes(content)
        raise
    subprocess.run(["git", "add", "--", *map(str, paths)], check=True)
    subprocess.run(["git", "commit", "-m", f"build: release {target}"], check=True)
    subprocess.run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], check=True)
    print(f"Prepared {tag}. Nothing pushed. Next: make release-push")


def push() -> None:
    clean_main()
    if run("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") != "origin/main":
        raise ValueError("Expected upstream origin/main.")
    version = current_version()
    version_tuple(version)
    tag = f"v{version}"
    head = run("git", "rev-parse", "HEAD")
    if run("git", "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        raise ValueError("Release tag must be annotated.")
    if run("git", "rev-parse", f"{tag}^{{commit}}") != head:
        raise ValueError("Release tag must point at HEAD.")
    if run("git", "log", "-1", "--format=%s") != f"build: release {version}":
        raise ValueError("HEAD must be the dedicated release commit.")
    subprocess.run(
        [
            "git",
            "push",
            "--atomic",
            "origin",
            "refs/heads/main:refs/heads/main",
            f"refs/tags/{tag}:refs/tags/{tag}",
        ],
        check=True,
    )
    refs = dict(
        line.split()[::-1]
        for line in run(
            "git",
            "ls-remote",
            "origin",
            "refs/heads/main",
            f"refs/tags/{tag}^{{}}",
        ).splitlines()
    )
    if refs.get("refs/heads/main") != head or refs.get(f"refs/tags/{tag}^{{}}") != head:
        raise ValueError("Push returned but remote refs do not match; inspect before retrying.")
    print(f"Verified origin/main and {tag} at {head}.")


def main() -> None:
    os.chdir(Path(__file__).resolve().parents[1])
    try:
        if sys.argv[1:] == ["--push"]:
            push()
        elif not sys.argv[1:]:
            prepare()
        else:
            raise ValueError("Run make release interactively, or make release-push.")
    except (ValueError, subprocess.CalledProcessError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
