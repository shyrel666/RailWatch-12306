#!/usr/bin/env bash
# Build an ad-hoc signed macOS DMG and ZIP for this Mac's architecture.
# Usage: ./package-macos.sh <version> [--install-deps]
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "=== RailWatch 12306 macOS Packaging ==="
echo

for tool in node npm python3; do
  if ! command -v "$tool" > /dev/null 2>&1; then
    echo "ERROR: $tool was not found in PATH." >&2
    exit 1
  fi
done

PACKAGE_VERSION="${1:-}"
INSTALL_DEPS="${2:-}"
if [ -z "$PACKAGE_VERSION" ]; then
  read -r -p "Enter package version, for example 0.6.0: " PACKAGE_VERSION
fi
if [ -z "$PACKAGE_VERSION" ]; then
  echo "ERROR: package version is required." >&2
  exit 1
fi
node -e "const v=process.argv[1]; if(!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(v)){console.error('Invalid version: '+v); process.exit(1)}" "$PACKAGE_VERSION"

case "$(uname -m)" in
  arm64) ARCH=arm64 ;;
  x86_64) ARCH=x64 ;;
  *) echo "ERROR: unsupported architecture $(uname -m)." >&2; exit 1 ;;
esac

echo "[1/5] Setting package version to $PACKAGE_VERSION"
npm version "$PACKAGE_VERSION" --no-git-tag-version --allow-same-version

echo
echo "[2/5] Checking Node dependencies"
if [ "$INSTALL_DEPS" = "--install-deps" ] || [ ! -f "node_modules/.package-lock.json" ]; then
  echo "Installing Node dependencies"
  npm ci
else
  echo "Skipping Node dependencies. Use \"$0 $PACKAGE_VERSION --install-deps\" to reinstall."
fi

echo
echo "[3/5] Checking Python packaging dependencies"
if [ "$INSTALL_DEPS" = "--install-deps" ] || ! python3 -c "import PyInstaller, keyring" > /dev/null 2>&1; then
  echo "Installing Python packaging dependencies"
  python3 -m pip install --upgrade pip
  python3 -m pip install -r requirements.txt pyinstaller
else
  echo "Skipping Python packaging dependencies. Use \"$0 $PACKAGE_VERSION --install-deps\" to reinstall."
fi

echo
echo "Cleaning previous release output"
rm -rf release

echo
echo "[4/5] Building ad-hoc signed $ARCH app"
# Same parameters as CI: ad-hoc signature, no notarization, manual updates.
CSC_IDENTITY_AUTO_DISCOVERY=false npm run package:mac -- "--$ARCH" \
  -c.mac.identity=- \
  -c.mac.notarize=false \
  -c.extraMetadata.railwatchMacUpdateMode=manual

echo
echo "Validating updater metadata assets"
node scripts/verify-update-metadata.mjs --version "$PACKAGE_VERSION" --arch "$ARCH" release/latest-mac.yml

echo
echo "[5/5] Packaging complete"
echo "Release assets to upload:"
ls -1 release/*.dmg release/*.zip release/*.blockmap release/latest-mac.yml
echo
echo "CI merges latest-mac.yml from both architectures; upload a single-architecture"
echo "latest-mac.yml by hand only if you also publish the other architecture's files."
