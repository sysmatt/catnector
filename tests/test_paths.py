"""Configuration locations and file permissions."""

from __future__ import annotations

import sys

import pytest

from catnector import paths


def test_env_override_wins(tmp_path, monkeypatch):
    """§4 is about moving these files around; the override must be absolute."""
    monkeypatch.setenv(paths.ENV_OVERRIDE, str(tmp_path))
    assert paths.config_dir() == tmp_path
    assert paths.rigs_path() == tmp_path / "rigs.ini"
    assert paths.sites_path() == tmp_path / "sites.ini"


def test_platform_default_is_under_the_home_directory(monkeypatch):
    monkeypatch.delenv(paths.ENV_OVERRIDE, raising=False)
    assert paths.config_dir().name == paths.APP_NAME


def test_first_run_writes_commented_examples(tmp_path, monkeypatch):
    """Someone opening the folder should find the schema, not an empty file."""
    monkeypatch.setenv(paths.ENV_OVERRIDE, str(tmp_path))
    paths.ensure_config_dir()
    rigs = (tmp_path / "rigs.ini").read_text()
    assert "model" in rigs and "connection" in rigs
    assert "THIS FILE CONTAINS CREDENTIALS" in (tmp_path / "sites.ini").read_text()


def test_examples_do_not_overwrite_real_config(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_OVERRIDE, str(tmp_path))
    paths.ensure_config_dir()
    (tmp_path / "rigs.ini").write_text("[Mine]\nmodel = 1035\n")
    paths.ensure_config_dir()
    assert "[Mine]" in (tmp_path / "rigs.ini").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_the_token_file_is_created_private(tmp_path, monkeypatch):
    """Plain text is deliberate; world-readable is not (§4.2)."""
    monkeypatch.setenv(paths.ENV_OVERRIDE, str(tmp_path))
    paths.ensure_config_dir()
    assert not paths.is_world_readable(tmp_path / "sites.ini")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_loose_token_file_is_detected(tmp_path):
    loose = tmp_path / "sites.ini"
    loose.write_text("token = secret")
    loose.chmod(0o644)
    assert paths.is_world_readable(loose)
    paths.restrict_permissions(loose)
    assert not paths.is_world_readable(loose)
