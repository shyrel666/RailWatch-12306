"""CI probe: confirm keyring writes land in the temporary default keychain.

Run it with the same overridden HOME as the smoke tests. A failure means the
test keychain setup is broken, not the runtime, so it is reported separately.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from railwatch_preferences import KEYCHAIN_SERVICE, MacSecretStore  # noqa: E402
from scripts.ci_keychain import use_test_keychain  # noqa: E402

PROBE_SERVICE = KEYCHAIN_SERVICE + ".ci-probe"


def in_keychain(account: str, keychain: str) -> bool:
    found = subprocess.run(["security", "find-generic-password", "-s", PROBE_SERVICE, "-a", account, keychain],
                           capture_output=True, text=True)
    return found.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keychain", required=True, help="path of the temporary default keychain")
    args = parser.parse_args()
    account = f"probe-{uuid.uuid4().hex[:12]}"
    store = MacSecretStore(service=PROBE_SERVICE, account=account)
    try:
        # Same preparation the smoke tests apply to their temporary HOME.
        use_test_keychain(os.environ["HOME"], args.keychain)
        store.write_all({"probe": "value"})
        if store.read_all() != {"probe": "value"}:
            raise RuntimeError("读回的条目与写入内容不一致")
        if not in_keychain(account, args.keychain):
            raise RuntimeError(f"条目没有写入临时钥匙串 {args.keychain}")
        store.delete()
        if store.read_all() is not None or in_keychain(account, args.keychain):
            raise RuntimeError("测试条目未能删除")
    except Exception as exc:
        print(f"测试钥匙串不可用: {exc}", file=sys.stderr)
        return 1
    print(f"Keychain probe passed: keyring uses {args.keychain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
