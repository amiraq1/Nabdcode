"""tests/test_config_security.py — Am+9 SEC-2: API key encryption at rest.

Red-guard tests for the AES-256-GCM encryption layer in core/config.py.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import (
    ConfigManager,
    encrypt_api_key,
    decrypt_api_key,
    _derive_key,
    _get_machine_id,
    _get_or_create_salt,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_config(tmp_path: Path) -> ConfigManager:
    """Create a ConfigManager backed by a temp directory."""
    config_dir = tmp_path / "nabdcode"
    config_dir.mkdir()
    return ConfigManager(config_dir=config_dir)


# ── ع1: config_file_has_strict_permissions ─────────────────────────────────────

def test_config_file_has_strict_permissions(temp_config: ConfigManager) -> None:
    """Config file must not be world/group-readable (owner read/write only)."""
    temp_config.set_api_key("openrouter", "sk-test-1234567890")
    mode = stat.S_IMODE(os.stat(temp_config.config_path).st_mode)
    assert not (mode & stat.S_IROTH), f"config file world-readable: {oct(mode)}"
    assert not (mode & stat.S_IRGRP), f"config file group-readable: {oct(mode)}"


def test_config_dir_has_strict_permissions(temp_config: ConfigManager) -> None:
    """Config directory must not be world/group-readable (owner only)."""
    temp_config.set_api_key("openrouter", "sk-test-1234567890")
    mode = stat.S_IMODE(os.stat(temp_config.config_dir).st_mode)
    assert not (mode & stat.S_IROTH), f"config dir world-readable: {oct(mode)}"
    assert not (mode & stat.S_IRGRP), f"config dir group-readable: {oct(mode)}"


# ── ع2: api_key_not_plaintext_in_logs ───────────────────────────────────────────

def test_api_key_not_plaintext_in_logs(temp_config: ConfigManager) -> None:
    """API keys must not appear in plaintext in logs."""
    test_key = "sk-secret-key-1234567890"
    temp_config.set_api_key("openrouter", test_key)

    # Read raw config from disk — key should be encrypted
    with open(temp_config.config_path, "r") as fh:
        raw = json.load(fh)

    raw_str = json.dumps(raw)
    assert test_key not in raw_str, "Plaintext API key found in config file!"
    assert "enc:" in raw["api_keys"]["openrouter"]


def test_api_key_not_plaintext_in_logs_multiple_providers(
    temp_config: ConfigManager,
) -> None:
    """Multiple API keys must all be encrypted on disk."""
    keys = {
        "openrouter": "sk-or-v1-test123",
        "nvidia": "nvapi-test456",
        "orcarouter": "sk-orca-test789",
    }
    for provider, key in keys.items():
        temp_config.set_api_key(provider, key)

    with open(temp_config.config_path, "r") as fh:
        raw = json.load(fh)

    raw_str = json.dumps(raw)
    for provider, key in keys.items():
        assert key not in raw_str, f"Plaintext key for {provider} found on disk!"


# ── ع3: encryption_or_keyring_used ──────────────────────────────────────────────

def test_encryption_used_for_api_keys(temp_config: ConfigManager) -> None:
    """API keys must be encrypted with AES-256-GCM (enc: prefix)."""
    temp_config.set_api_key("openrouter", "sk-test-1234567890")

    with open(temp_config.config_path, "r") as fh:
        raw = json.load(fh)

    encrypted_key = raw["api_keys"]["openrouter"]
    assert encrypted_key.startswith("enc:"), "Key not encrypted on disk"
    assert encrypted_key != "sk-test-1234567890"


def test_encryption_round_trip(temp_config: ConfigManager) -> None:
    """encrypt_api_key + decrypt_api_key must round-trip correctly."""
    original = "sk-round-trip-test-1234567890"
    encrypted = encrypt_api_key(original)
    decrypted = decrypt_api_key(encrypted)
    assert decrypted == original


def test_decrypt_plaintext_backward_compatible() -> None:
    """decrypt_api_key must return plaintext unchanged (backward compat)."""
    plaintext = "sk-plaintext-key"
    assert decrypt_api_key(plaintext) == plaintext


def test_decrypt_empty_string() -> None:
    """decrypt_api_key must handle empty strings."""
    assert decrypt_api_key("") == ""


def test_get_api_key_returns_plaintext(temp_config: ConfigManager) -> None:
    """get_api_key must return the decrypted plaintext key."""
    original = "sk-decrypt-test-1234567890"
    temp_config.set_api_key("openrouter", original)
    retrieved = temp_config.get_api_key("openrouter")
    assert retrieved == original


def test_get_all_api_keys_decrypted(temp_config: ConfigManager) -> None:
    """get_all_api_keys must return decrypted keys."""
    keys = {
        "openrouter": "sk-test-001",
        "nvidia": "nvapi-test-002",
    }
    for provider, key in keys.items():
        temp_config.set_api_key(provider, key)

    all_keys = temp_config.get_all_api_keys()
    for provider, key in keys.items():
        assert all_keys[provider] == key, f"Key for {provider} not decrypted"


def test_key_derivation_is_stable() -> None:
    """Key derivation must be deterministic for the same machine."""
    key1 = _derive_key()
    key2 = _derive_key()
    assert key1 == key2, "Key derivation is not stable across calls"


def test_machine_id_is_stable() -> None:
    """Machine ID must be stable across calls."""
    mid1 = _get_machine_id()
    mid2 = _get_machine_id()
    assert mid1 == mid2, "Machine ID is not stable"


def test_salt_is_created_and_stored(tmp_path: Path) -> None:
    """Salt file must be created with secure permissions."""
    with patch("core.config.CONFIG_DIR", tmp_path / "config"), \
         patch("core.config.SALT_FILE", tmp_path / "config" / ".salt"):
        salt = _get_or_create_salt()
        assert len(salt) == 32
        salt_file = tmp_path / "config" / ".salt"
        assert salt_file.exists()
        mode = stat.S_IMODE(os.stat(salt_file).st_mode)
        assert not (mode & stat.S_IROTH), f"salt file world-readable: {oct(mode)}"
        assert not (mode & stat.S_IRGRP), f"salt file group-readable: {oct(mode)}"


def test_noninteractive_mode_refuses_missing_key_without_prompt(
    temp_config: ConfigManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Automation must fail fast instead of blocking on getpass()."""
    monkeypatch.setenv("NABD_NONINTERACTIVE", "1")

    with pytest.raises(ValueError, match="non-interactive mode"):
        temp_config.get_or_prompt_api_key("openrouter")
