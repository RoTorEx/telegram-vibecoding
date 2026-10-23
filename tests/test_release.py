import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def release_repo(tmp_path):
    source = Path(__file__).resolve().parents[1]
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ["pyproject.toml", "uv.lock", "README.md", "CHANGELOG.md", ".gitignore"]:
        shutil.copyfile(source / name, repo / name)
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text().replace("## [Unreleased]", "## [Unreleased]\n\n- Release fixture.", 1)
    )
    shutil.copytree(source / "src", repo / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "scripts").mkdir()
    shutil.copyfile(source / "scripts/release.py", repo / "scripts/release.py")
    (repo / "Makefile").write_text("check:\n\t@true\n")
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Release test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Release test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }

    def run(*args, input=None, check=True):
        return subprocess.run(
            args, cwd=repo, env=environment, text=True, input=input, capture_output=True, check=check
        )

    run("git", "init", "-q", "-b", "main")
    run("git", "add", ".")
    run("git", "commit", "-qm", "Initial commit")
    remote = tmp_path / "remote.git"
    run("git", "init", "--bare", str(remote))
    run("git", "remote", "add", "origin", str(remote))
    run("git", "push", "-u", "origin", "main")
    return repo, run


def test_release_updates_cli_wheel_changelog_and_pushes_only_its_tag(release_repo, tmp_path):
    repo, run = release_repo
    initial = run("git", "rev-parse", "HEAD").stdout.strip()
    run("git", "tag", "unrelated-local-tag")
    run(sys.executable, "scripts/release.py", input="999.0.0\n")
    assert run("uv", "run", "--frozen", "telegram-vibecoding", "--version").stdout.strip() == "999.0.0"
    assert run("git", "cat-file", "-t", "v999.0.0").stdout.strip() == "tag"
    assert run("git", "rev-parse", "v999.0.0^{commit}").stdout == run("git", "rev-parse", "HEAD").stdout
    assert run("git", "log", "-1", "--format=%s").stdout.strip() == "build: release 999.0.0"
    changelog = (repo / "CHANGELOG.md").read_text()
    assert changelog.index("## [Unreleased]") < changelog.index("## [999.0.0]")
    artifacts = tmp_path / "artifacts"
    run("uv", "build", "--offline", "--wheel", "--out-dir", str(artifacts))
    with zipfile.ZipFile(next(artifacts.glob("*.whl"))) as archive:
        metadata = next(p for p in archive.namelist() if p.endswith(".dist-info/METADATA"))
        assert "Version: 999.0.0\n" in archive.read(metadata).decode()
    assert not run("git", "status", "--porcelain").stdout.strip()
    assert run("git", "ls-remote", "origin", "refs/heads/main").stdout.split()[0] == initial
    run(sys.executable, "scripts/release.py", "--push")
    remote_refs = run("git", "ls-remote", "origin").stdout
    assert "refs/tags/v999.0.0" in remote_refs
    assert "unrelated-local-tag" not in remote_refs
    assert run(sys.executable, "scripts/release.py", input="999.0.0\n", check=False).returncode != 0


def test_dirty_work_and_failed_checks_do_not_mutate_release_state(release_repo):
    repo, run = release_repo
    tracked = run("git", "ls-files").stdout.splitlines()
    before = {p: (repo / p).read_bytes() for p in tracked}
    (repo / "user-work.txt").write_text("Preserve this work")
    assert run(sys.executable, "scripts/release.py", input="999.0.0\n", check=False).returncode != 0
    assert before == {p: (repo / p).read_bytes() for p in tracked}
    (repo / "user-work.txt").unlink()
    (repo / "Makefile").write_text("check:\n\t@false\n")
    run("git", "add", "Makefile")
    run("git", "commit", "-qm", "test: fail required checks")
    head = run("git", "rev-parse", "HEAD").stdout
    assert run(sys.executable, "scripts/release.py", input="999.0.0\n", check=False).returncode != 0
    assert run("git", "rev-parse", "HEAD").stdout == head
    assert not run("git", "status", "--porcelain").stdout.strip()
    assert not run("git", "tag", "--list").stdout.strip()


def test_release_push_rejects_tag_that_does_not_identify_head(release_repo):
    repo, run = release_repo
    run(sys.executable, "scripts/release.py", input="999.0.0\n")
    (repo / "README.md").write_text("Unreleased change\n")
    run("git", "add", "README.md")
    run("git", "commit", "-qm", "docs: change after release")
    result = run(sys.executable, "scripts/release.py", "--push", check=False)
    assert result.returncode != 0
    assert "must point at HEAD" in result.stderr
    assert not run("git", "ls-remote", "origin", "refs/tags/v999.0.0").stdout.strip()
