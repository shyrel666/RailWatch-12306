"""Keep unit tests off the macOS login keychain.

On macOS a RailWatchBridge built without a secret store uses the user's own
keychain item. A test that saves notification settings or clears local data
through such a bridge would overwrite or delete the developer's real
credentials, or wait on an authorization prompt on a headless runner.

Importing this module refuses that for the rest of the process: a
MacSecretStore without an injected backend raises instead of opening the
keychain. A test module whose bridges do reach the store states so with

    setUpModule = isolate_system_keychain

and its bridges then share an in-memory keychain. Nothing changes on other
systems, where a bridge has no secret store.
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from typing import Dict, Iterator, Optional, Tuple
from unittest.mock import patch

from railwatch_preferences import MacSecretStore


class MemoryKeyring:
    """The three keyring calls MacSecretStore makes, kept in a dict."""

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> Optional[str]:
        return self.items.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.items[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.items.pop((service, account), None)


def _injected_backend_only(store: MacSecretStore):
    if store._backend is None:
        raise AssertionError(
            "A test reached the macOS login keychain. Give RailWatchBridge a secret_store, or set "
            "setUpModule = isolate_system_keychain (scripts.keychain_isolation) in the test module.")
    return store._backend


MacSecretStore._keyring = _injected_backend_only


@contextmanager
def in_memory_keychain() -> Iterator[MemoryKeyring]:
    """Bridges built without a secret store share one in-memory keychain."""
    keyring = MemoryKeyring()
    with patch("railwatch_bridge.MacSecretStore", lambda: MacSecretStore(backend=keyring)):
        yield keyring


def isolate_system_keychain() -> None:
    """A setUpModule: keep the in-memory keychain in place for every test of the module."""
    unittest.enterModuleContext(in_memory_keychain())
