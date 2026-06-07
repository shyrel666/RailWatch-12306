"""ChromeDriver version detection and auto-download manager."""

from __future__ import annotations

import io
import json
import os
import platform
import re
import sys
import zipfile
from typing import Optional, Tuple

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    URLLIB_AVAILABLE = True
except ImportError:
    URLLIB_AVAILABLE = False


# Chrome for Testing JSON API (Chrome 115+)
CFT_URL = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
# Pre-115 ChromeDriver storage API
LEGACY_URL_PREFIX = "https://chromedriver.storage.googleapis.com"


def _http_get(url: str, timeout: int = 30) -> bytes:
    """Fetch URL content, preferring requests (with redirects) over urllib."""
    if REQUESTS_AVAILABLE:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.content
    if URLLIB_AVAILABLE:
        req = Request(url, headers={"User-Agent": "RailWatch/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    raise RuntimeError("No HTTP library available (need requests or urllib).")


def detect_chrome_version() -> Optional[str]:
    """Detect installed Chrome/Chromium major version string (e.g. '137').

    Checks Windows registry, common install paths, and linux paths.
    Returns None if Chrome is not found.
    """
    system = platform.system()

    if system == "Windows":
        return _detect_chrome_windows()
    if system == "Darwin":
        return _detect_chrome_macos()
    return _detect_chrome_linux()


def _detect_chrome_windows() -> Optional[str]:
    # Try registry first
    try:
        import winreg

        for hive, flag in [
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
        ]:
            try:
                key = winreg.OpenKey(
                    hive,
                    r"SOFTWARE\Google\Chrome\BLBeacon",
                    0,
                    flag,
                )
                version, _ = winreg.QueryValueEx(key, "version")
                winreg.CloseKey(key)
                if version:
                    return version.split(".")[0]
            except OSError:
                pass
    except ImportError:
        pass

    # Fallback: check common paths
    for path in [
        os.path.join(
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            "Google", "Chrome", "Application", "chrome.exe",
        ),
        os.path.join(
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            "Google", "Chrome", "Application", "chrome.exe",
        ),
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Google", "Chrome", "Application", "chrome.exe",
        ),
    ]:
        if path and os.path.isfile(path):
            try:
                version = _read_exe_version(path)
                if version:
                    return version.split(".")[0]
            except Exception:
                pass

    return None


def _read_exe_version(path: str) -> Optional[str]:
    """Infer Chrome version from its install directory name.

    Chrome installs as: .../Application/<version>/chrome.exe
    """
    parent = os.path.dirname(path)
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", os.path.basename(parent)):
        return os.path.basename(parent)
    return None


def _detect_chrome_macos() -> Optional[str]:
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for p in paths:
        if os.path.isfile(p):
            try:
                import subprocess
                result = subprocess.run(
                    [p, "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout.strip())
                if m:
                    return m.group(1)
            except Exception:
                pass
    return None


def _detect_chrome_linux() -> Optional[str]:
    import subprocess
    for cmd in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
        try:
            result = subprocess.run(
                [cmd, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout.strip())
            if m:
                return m.group(1)
        except Exception:
            pass
    return None


def get_chromedriver_download_url(major_version: str) -> Optional[Tuple[str, str]]:
    """Return (download_url, version_string) for the given Chrome major version.

    For Chrome 115+, uses the Chrome for Testing JSON API.
    For Chrome versions before 115, uses the pre-115 storage API.
    """
    major = int(major_version)

    if major >= 115:
        return _get_cft_url(major_version)
    return _get_pre115_url(major_version)


def _get_cft_url(major_version: str) -> Optional[Tuple[str, str]]:
    """Chrome for Testing API (Chrome 115+)."""
    try:
        data = json.loads(_http_get(CFT_URL))
    except Exception:
        return None

    platform_name = _cft_platform_name()
    if not platform_name:
        return None

    # Search from newest to oldest for matching major version
    for entry in reversed(data.get("versions", [])):
        ver = entry.get("version", "")
        if not ver.startswith(major_version + "."):
            continue
        downloads = entry.get("downloads", {}).get("chromedriver", [])
        for d in downloads:
            if d.get("platform") == platform_name:
                return d["url"], ver
    return None


def _cft_platform_name() -> Optional[str]:
    """Return the Chrome for Testing platform string for this OS."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "win32"
    if system == "Darwin":
        return "mac-arm64" if machine in ("arm64", "aarch64") else "mac-x64"
    if system == "Linux":
        return "linux64"
    return None


def _get_pre115_url(major_version: str) -> Optional[Tuple[str, str]]:
    """ChromeDriver storage API for Chrome versions before 115."""
    # Get the latest patch version for this major
    try:
        data = _http_get(f"{LEGACY_URL_PREFIX}/LATEST_RELEASE_{major_version}")
        full_version = data.decode("utf-8").strip()
    except Exception:
        return None

    platform_tag = _pre115_platform_tag()
    url = f"{LEGACY_URL_PREFIX}/{full_version}/chromedriver_{platform_tag}.zip"
    return url, full_version


def _pre115_platform_tag() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "win32"
    if system == "Darwin":
        return "mac64"  # Pre-115 downloads only expose mac64.
    return "linux64"


def download_and_install_chromedriver(
    target_dir: str,
    major_version: Optional[str] = None,
    log_callback=None,
) -> str:
    """Download ChromeDriver and install to target_dir.

    Args:
        target_dir: Directory to save chromedriver executable.
        major_version: Chrome major version. Auto-detected if None.
        log_callback: Optional callable for log messages.

    Returns:
        Path to installed chromedriver executable.

    Raises:
        RuntimeError: If Chrome not found, download fails, etc.
    """
    log = log_callback or (lambda _: None)

    if not major_version:
        major_version = detect_chrome_version()
        if not major_version:
            raise RuntimeError(
                "未检测到 Chrome 浏览器。请先安装 Chrome：https://www.google.com/chrome/"
            )

    log(f"检测到 Chrome 版本: {major_version}")

    result = get_chromedriver_download_url(major_version)
    if not result:
        raise RuntimeError(
            f"未找到 Chrome {major_version} 对应的 ChromeDriver 下载地址。"
            f"\n请手动下载: https://googlechromelabs.github.io/chrome-for-testing/"
        )

    url, full_version = result
    log(f"正在下载 ChromeDriver {full_version}...")

    try:
        zip_data = _http_get(url)
    except Exception as exc:
        raise RuntimeError(f"下载 ChromeDriver 失败: {exc}") from exc

    # Extract chromedriver from zip
    os.makedirs(target_dir, exist_ok=True)
    exe_name = "chromedriver.exe" if platform.system() == "Windows" else "chromedriver"

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            # Find the chromedriver executable in the zip (may be nested)
            target_name = None
            for name in zf.namelist():
                basename = os.path.basename(name)
                if basename == exe_name:
                    target_name = name
                    break
            if not target_name:
                # Try case-insensitive match
                for name in zf.namelist():
                    if name.lower().endswith(exe_name.lower()):
                        target_name = name
                        break
            if not target_name:
                raise RuntimeError(f"压缩包中未找到 {exe_name}")

            with zf.open(target_name) as src:
                content = src.read()

    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"下载的文件不是有效的 ZIP: {exc}") from exc

    dest_path = os.path.join(target_dir, exe_name)
    # Write to temp file first, then rename atomically
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        # On Windows, need to remove dest first if it exists
        if os.path.exists(dest_path):
            os.replace(tmp_path, dest_path)
        else:
            os.rename(tmp_path, dest_path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    # Make executable on non-Windows
    if platform.system() != "Windows":
        os.chmod(dest_path, 0o755)

    log(f"ChromeDriver {full_version} 已安装到: {dest_path}")
    return dest_path


def get_chrome_version_info() -> str:
    """Get a human-readable Chrome version info string for display."""
    ver = detect_chrome_version()
    if ver:
        return f"Chrome {ver}"
    return "未检测到 Chrome"
