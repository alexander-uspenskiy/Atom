"""Connector secrets live in the OS keychain (macOS Keychain, Windows Credential Manager, Secret Service), not the DB."""
from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from ..stores import Invalid

SERVICE = "atom-connector"


def get(name: str, key: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, f"{name}:{key}")
    except KeyringError:
        return None


def put(name: str, key: str, value: str) -> None:
    try:
        keyring.set_password(SERVICE, f"{name}:{key}", value)
    except KeyringError as e:
        raise Invalid(f"Could not store the secret in the system keychain: {e}") from e


def delete(name: str, key: str) -> None:
    try:
        keyring.delete_password(SERVICE, f"{name}:{key}")
    except (PasswordDeleteError, KeyringError):
        pass
