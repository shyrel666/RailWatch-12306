"""ChromeDriver version detection and auto-download manager."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import io
import json
import os
import platform
import plistlib
import re
import sys
import tempfile
import time
import zipfile
from typing import Callable, Iterable, Optional, Tuple

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
    from urllib.error import HTTPError, URLError

    class _RefuseRedirect(HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    _PUBLISHER_OPENER = build_opener(_RefuseRedirect)
    URLLIB_AVAILABLE = True
except ImportError:
    URLLIB_AVAILABLE = False


# Chrome for Testing JSON APIs (Chrome 115+)
CFT_URL = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
CFT_MILESTONE_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/latest-versions-per-milestone-with-downloads.json"
)
CFT_BINARY_PREFIX = "https://storage.googleapis.com/chrome-for-testing-public"
# Pre-115 ChromeDriver storage API
LEGACY_URL_PREFIX = "https://chromedriver.storage.googleapis.com"

# npmmirror China mirror endpoints (preferred first, with automatic official fallback)
NPMMIRROR_CFT_API_PREFIX = "https://registry.npmmirror.com/-/binary/chrome-for-testing"
NPMMIRROR_CFT_CDN_PREFIX = "https://cdn.npmmirror.com/binaries/chrome-for-testing"
NPMMIRROR_PATCH_VERSIONS_URL = f"{NPMMIRROR_CFT_API_PREFIX}/latest-patch-versions-per-build.json"
NPMMIRROR_CFT_URL = f"{NPMMIRROR_CFT_API_PREFIX}/known-good-versions-with-downloads.json"
NPMMIRROR_LEGACY_API_PREFIX = "https://registry.npmmirror.com/-/binary/chromedriver"
NPMMIRROR_LEGACY_CDN_PREFIX = "https://cdn.npmmirror.com/binaries/chromedriver"
CHROME_DOWNLOAD_URL = "https://www.google.cn/chrome/"

_METADATA_TIMEOUT = 15
_MAX_MIRROR_PATCH_CANDIDATES = 3
_DOWNLOAD_CHUNK_SIZE = 16 * 1024
_PROGRESS_INTERVAL = 0.25
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_DRIVER_BYTES = 128 * 1024 * 1024

# SHA-256 of the versioned Google Chrome for Testing ZIPs. New versions can
# still be installed directly from the publisher before a mirror pin is added.
_ARCHIVE_SHA256 = {
    ("158.0.8127.36", "win32"): "504d090ec0cac53a12c5cd038bccae982cee77be1e7de34f08ed8acb57fcb563",
    ("158.0.8127.36", "mac-x64"): "707e35dcfc37c73305ceea27b8a3dba357b3f663562790975962293ad37efe1d",
    ("158.0.8127.36", "mac-arm64"): "e44347354ea6a7b666e4ef03803974e1344f78ce9c4466acd896ea6af53136e8",
    ("158.0.8127.36", "linux64"): "d20e70d69d68c5c983e2526452ed0779fd65dc4ade5d6741f1bb3d0d82754d3a",
}


def _report_progress(callback: Optional[Callable[[dict], None]], payload: dict) -> None:
    """Progress is advisory; a disconnected observer must not abort installation."""
    if callback is not None:
        try:
            callback(payload)
        except Exception:
            pass


def _read_download_chunks(
    chunks: Iterable[bytes],
    headers,
    progress_callback: Callable[[dict], None],
    started_at: float,
    write=None,
    limit: int = _MAX_ARCHIVE_BYTES,
    publisher: bool = False,
) -> Optional[bytes]:
    """Collect a response while reporting measured transfer progress, at most 4 Hz."""
    try:
        total = int(headers.get("Content-Length", ""))
    except (TypeError, ValueError):
        total = 0
    # requests decodes compressed responses; their Content-Length is not the size
    # of the decoded chunks, so do not derive a misleading percentage or ETA.
    if total <= 0 or headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
        total = None

    downloaded = 0
    last_reported_at = started_at
    if total is not None and total > limit:
        raise ValueError("下载超过大小限制")
    checksum = None
    if publisher:
        # TLS authenticates the Google object. Its published MD5 also detects transfer corruption.
        hashes = (",".join(headers.get_all("x-goog-hash", [])) if hasattr(headers, "get_all")
                  else headers.get("x-goog-hash", ""))
        expected = next((part.strip()[4:] for part in hashes.split(",") if part.strip().startswith("md5=")), "")
        if not expected:
            raise _CandidateDownloadError("官方响应缺少对象校验值")
        checksum = hashlib.md5(usedforsecurity=False)
    content = io.BytesIO() if write is None else None
    write_chunk = content.write if content is not None else write

    def report(now: float) -> None:
        elapsed = max(0.0, now - started_at)
        speed = downloaded / elapsed if downloaded and elapsed >= 0.5 else None
        _report_progress(progress_callback, {
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "bytes_per_second": speed,
            "eta_seconds": max(0.0, (total - downloaded) / speed) if total and speed else None,
            "elapsed_seconds": elapsed,
        })

    report(time.monotonic())
    for chunk in chunks:
        if not chunk:
            continue
        downloaded += len(chunk)
        if downloaded > limit:
            raise ValueError("下载超过大小限制")
        if checksum is not None:
            checksum.update(chunk)
        write_chunk(chunk)
        if total is not None and downloaded > total:
            # A stale/misreported length cannot be used for progress estimates.
            total = None
        now = time.monotonic()
        if now - last_reported_at >= _PROGRESS_INTERVAL:
            report(now)
            last_reported_at = now
    if total is not None and downloaded < total:
        raise IOError(f"下载不完整：收到 {downloaded} / {total} 字节")
    if checksum is not None and base64.b64encode(checksum.digest()).decode("ascii") != expected:
        raise _CandidateDownloadError("官方驱动文件校验失败")
    report(time.monotonic())
    return content.getvalue() if content is not None else None


def _http_get(
    url: str,
    timeout: int = 30,
    progress_callback: Optional[Callable[[dict], None]] = None,
    *, write=None, publisher=False,
) -> Optional[bytes]:
    """Stream archives to disk and keep metadata responses bounded."""
    headers = {"User-Agent": "RailWatch/1.0", "Accept-Encoding": "identity"}
    started_at = time.monotonic()
    if REQUESTS_AVAILABLE:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=not publisher, stream=True)
        try:
            resp.raise_for_status()
            if publisher and (resp.is_redirect is True or (type(resp.status_code) is int and 300 <= resp.status_code < 400)):
                raise ValueError("官方驱动地址发生重定向")
            return _read_download_chunks(resp.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE), resp.headers,
                                         progress_callback, started_at, write, _MAX_ARCHIVE_BYTES, publisher)
        finally:
            resp.close()
    if URLLIB_AVAILABLE:
        req = Request(url, headers=headers)
        try:
            response = _PUBLISHER_OPENER.open(req, timeout=timeout) if publisher else urlopen(req, timeout=timeout)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if publisher and 300 <= code < 400:
                raise ValueError("官方驱动地址发生重定向") from exc
            raise
        with response as resp:
            if publisher and resp.geturl() != url:
                raise ValueError("官方驱动地址发生重定向")
            return _read_download_chunks(iter(lambda: resp.read(_DOWNLOAD_CHUNK_SIZE), b""), resp.headers,
                                         progress_callback, started_at, write, _MAX_ARCHIVE_BYTES, publisher)
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


def detect_chromedriver_version(executable_path: str) -> Optional[str]:
    """Return the full version string reported by a ChromeDriver executable (e.g. '148.0.7778.178')."""
    if not executable_path or not os.path.isfile(executable_path):
        return None
    try:
        import subprocess

        result = subprocess.run(
            [executable_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        match = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout or "")
        if match:
            return match.group(0)
    except Exception:
        return None
    return None


def _read_exe_version(path: str) -> Optional[str]:
    """Infer Chrome version from its install directory name.

    Chrome installs as: .../Application/<version>/chrome.exe
    """
    parent = os.path.dirname(path)
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", os.path.basename(parent)):
        return os.path.basename(parent)
    return None


def _read_macos_plist_version(binary_path: str) -> Optional[str]:
    """Read Chrome/Chromium major version from Contents/Info.plist without launching the app."""
    contents_dir = os.path.dirname(os.path.dirname(binary_path))
    plist_path = os.path.join(contents_dir, "Info.plist")
    if not os.path.isfile(plist_path):
        return None
    try:
        with open(plist_path, "rb") as handle:
            info = plistlib.load(handle)
        if not isinstance(info, dict):
            return None
        for key in ("CFBundleShortVersionString", "CFBundleVersion", "KSVersion"):
            raw = info.get(key)
            if isinstance(raw, str):
                match = re.search(r"(\d+)\.\d+\.\d+(?:\.\d+)?", raw.strip())
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


def _detect_chrome_macos() -> Optional[str]:
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        # Users without admin rights install Chrome into their own Applications folder.
        os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for p in paths:
        if not os.path.isfile(p):
            continue
        major = _read_macos_plist_version(p)
        if major:
            return major
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


@dataclass(frozen=True)
class _DownloadCandidate:
    url: str
    version: str
    source_label: str


class _CandidateDownloadError(RuntimeError):
    """Error during downloading, unpacking, or verifying a candidate binary."""


class _LocalInstallError(RuntimeError):
    """Filesystem failure while preparing target_dir or writing ChromeDriver locally."""


def _prepare_target_dir(target_dir: str) -> None:
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as exc:
        raise _LocalInstallError(f"准备 ChromeDriver 安装目录失败: {exc}") from exc


def _fetch_metadata(url: str, progress_callback: Optional[Callable[[dict], None]] = None) -> bytes:
    """Fetch small release metadata with a shorter timeout so dead hosts fail fast."""
    if progress_callback is not None:
        _report_progress(progress_callback, {
            "downloaded_bytes": None, "total_bytes": None, "bytes_per_second": None,
            "eta_seconds": None, "elapsed_seconds": None,
        })
        return _http_get(url, timeout=_METADATA_TIMEOUT, progress_callback=progress_callback)
    return _http_get(url, timeout=_METADATA_TIMEOUT)


def _is_http_404(exc: Exception) -> bool:
    """Return True only when an HTTP endpoint explicitly reports 404 Not Found."""
    if getattr(exc, "code", None) == 404:
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _parse_version_tuple(version: str) -> Optional[Tuple[int, ...]]:
    """Parse dotted numeric version strings for deterministic descending comparisons."""
    parts = version.strip().strip("/").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _cft_mirror_zip_url(version: str, platform_name: str) -> str:
    return f"{NPMMIRROR_CFT_CDN_PREFIX}/{version}/{platform_name}/chromedriver-{platform_name}.zip"


def _cft_official_zip_url(version: str, platform_name: str) -> str:
    return f"{CFT_BINARY_PREFIX}/{version}/{platform_name}/chromedriver-{platform_name}.zip"


def _build_cft_candidates(
    version: str,
    platform_name: str,
    *,
    mirror_first: bool = True,
) -> list[_DownloadCandidate]:
    mirror = _DownloadCandidate(_cft_mirror_zip_url(version, platform_name), version, "npmmirror 镜像")
    official = _DownloadCandidate(
        _cft_official_zip_url(version, platform_name),
        version,
        "官方源",
    )
    return [mirror, official] if mirror_first else [official, mirror]


def _build_pre115_candidates(
    version: str,
    platform_tag: str,
    *,
    mirror_first: bool = True,
) -> list[_DownloadCandidate]:
    mirror = _DownloadCandidate(
        f"{NPMMIRROR_LEGACY_CDN_PREFIX}/{version}/chromedriver_{platform_tag}.zip",
        version,
        "npmmirror 镜像",
    )
    official = _DownloadCandidate(
        f"{LEGACY_URL_PREFIX}/{version}/chromedriver_{platform_tag}.zip",
        version,
        "官方源",
    )
    return [mirror, official] if mirror_first else [official, mirror]


def _find_platform_chromedriver_url(entry: dict, platform_name: str) -> Optional[str]:
    downloads = entry.get("downloads", {}).get("chromedriver", [])
    if not isinstance(downloads, list):
        return None
    for item in downloads:
        if isinstance(item, dict) and item.get("platform") == platform_name:
            url = item.get("url")
            if isinstance(url, str) and url:
                return url
    return None


def _extract_cft_match_from_versions(
    data: dict,
    major_version: str,
    platform_name: str,
) -> Optional[Tuple[str, str]]:
    """Return (official_url, highest_matching_version) from a CfT known-good JSON payload."""
    versions = data.get("versions", []) if isinstance(data, dict) else []
    prefix = f"{major_version}."
    best_key: Optional[Tuple[int, ...]] = None
    best_result: Optional[Tuple[str, str]] = None
    for entry in versions:
        if not isinstance(entry, dict):
            continue
        ver = str(entry.get("version", ""))
        if not ver.startswith(prefix):
            continue
        parsed = _parse_version_tuple(ver)
        if parsed is None:
            continue
        official_url = _find_platform_chromedriver_url(entry, platform_name)
        if not official_url:
            continue
        if best_key is None or parsed > best_key:
            best_key = parsed
            best_result = (official_url, ver)
    return best_result


def _mirror_has_cft_binary(
    version: str, platform_name: str, progress_callback: Optional[Callable[[dict], None]] = None,
) -> bool:
    """Confirm that chromedriver-{platform}.zip exists in npmmirror for the given build."""
    dir_url = f"{NPMMIRROR_CFT_API_PREFIX}/{version}/{platform_name}/"
    try:
        entries = json.loads(_fetch_metadata(dir_url, progress_callback))
    except Exception:
        return False
    if not isinstance(entries, list):
        return False
    expected_name = f"chromedriver-{platform_name}.zip"
    return any(
        isinstance(item, dict)
        and item.get("name") == expected_name
        and item.get("type") == "file"
        for item in entries
    )


def _fetch_lightweight_json(
    url: str, progress_callback: Optional[Callable[[dict], None]] = None,
) -> Tuple[Optional[dict], bool]:
    """Fetch a small JSON index; return (data_or_none, should_try_same_host_fallback)."""
    try:
        data = json.loads(_fetch_metadata(url, progress_callback))
    except Exception as exc:
        return None, _is_http_404(exc)
    return (data if isinstance(data, dict) else None), True


def _resolve_cft_from_known_good(
    metadata_url: str,
    major_version: str,
    platform_name: str,
    *,
    mirror_first: bool,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> list[_DownloadCandidate]:
    """Resolve ChromeDriver URLs from a full known-good-versions JSON endpoint."""
    try:
        full_data = json.loads(_fetch_metadata(metadata_url, progress_callback))
    except Exception:
        return []
    match = _extract_cft_match_from_versions(full_data, major_version, platform_name)
    if not match:
        return []
    _, ver = match
    return _build_cft_candidates(ver, platform_name, mirror_first=mirror_first)


def _ranked_patch_versions(patch_data: Optional[dict], major_version: str) -> list[str]:
    """Extract unique matching patch versions ordered highest-first by version tuple."""
    if not isinstance(patch_data, dict):
        return []
    builds = patch_data.get("builds", {})
    if not isinstance(builds, dict):
        return []
    prefix = f"{major_version}."
    ranked: list[Tuple[Tuple[int, ...], str]] = []
    for entry in builds.values():
        if not isinstance(entry, dict):
            continue
        ver = str(entry.get("version", ""))
        if not ver.startswith(prefix):
            continue
        parsed = _parse_version_tuple(ver)
        if parsed is not None:
            ranked.append((parsed, ver))
    ranked.sort(key=lambda item: item[0], reverse=True)
    unique: list[str] = []
    for _, ver in ranked:
        if ver not in unique:
            unique.append(ver)
    return unique


def _resolve_cft_mirror_candidates(
    major_version: str, platform_name: str, progress_callback: Optional[Callable[[dict], None]] = None,
) -> list[_DownloadCandidate]:
    """Resolve ChromeDriver URLs from npmmirror, preferring lightweight patch metadata."""
    patch_data, allow_same_host_fallback = _fetch_lightweight_json(NPMMIRROR_PATCH_VERSIONS_URL, progress_callback)
    if not allow_same_host_fallback:
        return []

    for ver in _ranked_patch_versions(patch_data, major_version)[:_MAX_MIRROR_PATCH_CANDIDATES]:
        if _mirror_has_cft_binary(ver, platform_name, progress_callback):
            return _build_cft_candidates(ver, platform_name, mirror_first=True)

    return _resolve_cft_from_known_good(
        NPMMIRROR_CFT_URL, major_version, platform_name, mirror_first=True, progress_callback=progress_callback,
    )


def _resolve_cft_official_candidates(
    major_version: str, platform_name: str, progress_callback: Optional[Callable[[dict], None]] = None,
) -> list[_DownloadCandidate]:
    """Resolve ChromeDriver URLs from official Chrome for Testing APIs."""
    milestone_data, allow_same_host_fallback = _fetch_lightweight_json(CFT_MILESTONE_URL, progress_callback)
    if not allow_same_host_fallback:
        return []

    if isinstance(milestone_data, dict):
        milestones = milestone_data.get("milestones", {})
        entry = milestones.get(major_version) if isinstance(milestones, dict) else None
        if isinstance(entry, dict):
            ver = str(entry.get("version", ""))
            official_url = _find_platform_chromedriver_url(entry, platform_name)
            if ver and official_url:
                return _build_cft_candidates(ver, platform_name, mirror_first=False)

    return _resolve_cft_from_known_good(
        CFT_URL, major_version, platform_name, mirror_first=False, progress_callback=progress_callback,
    )


def _resolve_pre115_candidates(
    major_version: str,
    platform_tag: str,
    *,
    api_prefix: str,
    mirror_first: bool,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> list[_DownloadCandidate]:
    try:
        data = _fetch_metadata(f"{api_prefix}/LATEST_RELEASE_{major_version}", progress_callback)
        full_version = data.decode("utf-8").strip()
    except Exception:
        return []
    if not full_version:
        return []
    return _build_pre115_candidates(full_version, platform_tag, mirror_first=mirror_first)


def _candidate_resolvers(
    major_version: str, progress_callback: Optional[Callable[[dict], None]] = None,
) -> list[Callable[[], list[_DownloadCandidate]]]:
    """Return lazy metadata resolvers ordered from npmmirror to official upstream."""
    major = int(major_version)
    if major >= 115:
        platform_name = _cft_platform_name()
        if not platform_name:
            return []
        return [
            lambda: _resolve_cft_mirror_candidates(major_version, platform_name, progress_callback),
            lambda: _resolve_cft_official_candidates(major_version, platform_name, progress_callback),
        ]
    platform_tag = _pre115_platform_tag()
    return [
        lambda: _resolve_pre115_candidates(
            major_version,
            platform_tag,
            api_prefix=NPMMIRROR_LEGACY_API_PREFIX,
            mirror_first=True,
            progress_callback=progress_callback,
        ),
        lambda: _resolve_pre115_candidates(
            major_version,
            platform_tag,
            api_prefix=LEGACY_URL_PREFIX,
            mirror_first=False,
            progress_callback=progress_callback,
        ),
    ]


def get_chromedriver_download_url(major_version: str) -> Optional[Tuple[str, str]]:
    """Return a pinned mirror or canonical publisher URL for the requested major."""
    major_str = str(int(major_version))
    for resolve in _candidate_resolvers(major_str):
        for candidate, _, _ in _trusted_downloads(resolve(), major_str):
            return candidate.url, candidate.version
    return None


def _get_cft_url(major_version: str) -> Optional[Tuple[str, str]]:
    """Chrome for Testing API (Chrome 115+), preferring npmmirror with official fallback."""
    return get_chromedriver_download_url(major_version)


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
    return get_chromedriver_download_url(major_version)


def _pre115_platform_tag() -> str:
    system = platform.system()
    if system == "Windows":
        return "win32"
    if system == "Darwin":
        return "mac64"  # Pre-115 downloads only expose mac64.
    return "linux64"


def _trusted_downloads(candidates, major):
    cft = int(major) >= 115
    platform_tag = _cft_platform_name() if cft else _pre115_platform_tag()
    for candidate in candidates:
        version = candidate.version
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", version) or version.split(".")[0] != major:
            continue
        official = (_cft_official_zip_url(version, platform_tag) if cft
                    else f"{LEGACY_URL_PREFIX}/{version}/chromedriver_{platform_tag}.zip")
        publisher = candidate.url == official
        pin = _ARCHIVE_SHA256.get((version, platform_tag))
        if publisher or pin:
            yield candidate, publisher, pin


def _copy_driver(archive, exe_name, output):
    try:
        with zipfile.ZipFile(archive) as zf:
            members = [entry for entry in zf.infolist()
                       if not entry.is_dir() and os.path.basename(entry.filename).lower() == exe_name.lower()]
            if len(members) != 1:
                raise _CandidateDownloadError(f"压缩包中缺少唯一的 {exe_name}")
            entry = members[0]
            if not 0 < entry.file_size <= _MAX_DRIVER_BYTES:
                raise _CandidateDownloadError("驱动文件大小异常")
            with zf.open(entry) as src:
                size = 0
                while chunk := src.read(_DOWNLOAD_CHUNK_SIZE):
                    size += len(chunk)
                    if size > _MAX_DRIVER_BYTES:
                        raise _CandidateDownloadError("驱动文件超过大小限制")
                    output.write(chunk)
    except zipfile.BadZipFile as exc:
        raise _CandidateDownloadError(f"下载的文件不是有效的 ZIP: {exc}") from exc


def _install_verified_binary(
    archive,
    target_dir: str,
    exe_name: str,
    expected_version: str,
) -> Tuple[str, str]:
    """Stage the authenticated archive and check its full version before atomic installation."""
    _prepare_target_dir(target_dir)
    dest_path = os.path.join(target_dir, exe_name)
    tmp_suffix = ".tmp.exe" if platform.system() == "Windows" else ".tmp"
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=f".{exe_name}.", suffix=tmp_suffix, dir=target_dir)
    except OSError as exc:
        raise _LocalInstallError(f"无法在目标目录创建 ChromeDriver 临时文件: {exc}") from exc

    fd_closed = False
    try:
        try:
            with os.fdopen(fd, "wb") as f:
                fd_closed = True
                _copy_driver(archive, exe_name, f)
            if platform.system() != "Windows":
                os.chmod(tmp_path, 0o755)
        except OSError as exc:
            if not fd_closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise _LocalInstallError(f"写入 ChromeDriver 临时文件失败: {exc}") from exc

        try:
            detected_version = detect_chromedriver_version(tmp_path)
            if not detected_version:
                raise _CandidateDownloadError("下载的 ChromeDriver 无法执行或版本校验失败")
            if detected_version != expected_version:
                raise _CandidateDownloadError(
                    f"ChromeDriver 版本校验不匹配：期望 {expected_version}，实际为 {detected_version}"
                )
        except _CandidateDownloadError:
            raise
        except Exception as exc:
            raise _CandidateDownloadError(f"校验临时 ChromeDriver 失败: {exc}") from exc

        try:
            os.replace(tmp_path, dest_path)
            if platform.system() != "Windows":
                os.chmod(dest_path, 0o755)
        except OSError as exc:
            raise _LocalInstallError(f"安装 ChromeDriver 到目标目录失败: {exc}") from exc
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    return dest_path, detected_version


def download_and_install_chromedriver(
    target_dir: str,
    major_version: Optional[str] = None,
    log_callback=None,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> str:
    """Download ChromeDriver and install to target_dir.

    Releases with a pinned SHA-256 can use npmmirror. Other versions use the
    canonical Google Storage asset for the platform, with TLS and its object
    checksum. Both paths verify the full driver version before installation.

    progress_callback receives complete snapshots with stage/message/source,
    byte counts, measured bytes_per_second and eta_seconds (None if unknown).
    Resolving metadata and downloading the archive are separate transfers;
    the transfer ETA never represents the whole environment check.
    """
    log = log_callback or (lambda _: None)

    def progress(stage: str, message: str, *, source=None, version=None, **metrics) -> None:
        _report_progress(progress_callback, {
            "stage": stage,
            "message": message,
            "source": source,
            "version": version,
            "downloaded_bytes": None,
            "total_bytes": None,
            "bytes_per_second": None,
            "eta_seconds": None,
            "elapsed_seconds": None,
            **metrics,
        })

    if not major_version:
        major_version = detect_chrome_version()
        if not major_version:
            raise RuntimeError(
                f"未检测到 Chrome 浏览器。请先安装 Chrome：{CHROME_DOWNLOAD_URL}"
            )
    else:
        major_version = str(major_version).strip()

    try:
        major_int = int(major_version)
    except ValueError as exc:
        raise RuntimeError(f"无效的 Chrome 主版本号: {major_version}") from exc
    major_version = str(major_int)

    log(f"检测到 Chrome 版本: {major_version}")

    exe_name = "chromedriver.exe" if platform.system() == "Windows" else "chromedriver"
    seen_urls: set[str] = set()
    errors: list[str] = []

    source = "npmmirror 镜像"

    def metadata_progress(metrics: dict) -> None:
        progress("resolving", f"正在从{source}获取驱动版本信息…", source=source, **metrics)

    resolvers = (_candidate_resolvers(major_version, metadata_progress)
                 if progress_callback is not None else _candidate_resolvers(major_version))
    for resolver_index, resolve in enumerate(resolvers):
        source = "npmmirror 镜像" if resolver_index == 0 else "官方源"
        progress("resolving", f"正在从{source}查找匹配 Chrome {major_version} 的驱动…", source=source)
        for candidate, publisher, pin in _trusted_downloads(resolve(), major_version):
            if candidate.url in seen_urls:
                continue
            seen_urls.add(candidate.url)
            log(f"正在从{candidate.source_label}下载 ChromeDriver {candidate.version}...")
            progress(
                "connecting", f"正在连接{candidate.source_label}，准备下载 ChromeDriver…",
                source=candidate.source_label, version=candidate.version,
            )
            try:
                _prepare_target_dir(target_dir)
                transfer = (lambda metrics: progress(
                    "downloading", f"正在从{candidate.source_label}下载 ChromeDriver {candidate.version}…",
                    source=candidate.source_label, version=candidate.version, **metrics,
                )) if progress_callback is not None else None
                try:
                    temporary = tempfile.TemporaryFile(dir=target_dir)
                except OSError as exc:
                    raise _LocalInstallError(f"无法创建驱动下载临时文件: {exc}") from exc
                with temporary as archive:
                    def store_archive(chunk):
                        try:
                            archive.write(chunk)
                        except OSError as exc:
                            raise _LocalInstallError(f"写入驱动压缩包失败: {exc}") from exc
                    _http_get(candidate.url, progress_callback=transfer, write=store_archive, publisher=publisher)
                    if pin:
                        archive.seek(0)
                        if hashlib.file_digest(archive, "sha256").hexdigest() != pin:
                            raise _CandidateDownloadError("ChromeDriver SHA-256 与官方固定摘要不一致")
                    archive.seek(0)
                    progress("extracting", "下载完成，正在解压 ChromeDriver…", source=candidate.source_label, version=candidate.version)
                    progress("installing", "正在校验版本并安装 ChromeDriver…", source=candidate.source_label, version=candidate.version)
                    dest_path, verified_version = _install_verified_binary(archive, target_dir, exe_name, candidate.version)
                log(f"ChromeDriver {verified_version} 已安装到: {dest_path}")
                progress(
                    "complete", f"ChromeDriver {verified_version} 安装完成",
                    source=candidate.source_label, version=verified_version,
                )
                return dest_path
            except _LocalInstallError as exc:
                raise RuntimeError(str(exc)) from exc
            except Exception as exc:
                errors.append(f"[{candidate.source_label}] {exc}")
                log(f"从{candidate.source_label}获取 ChromeDriver 失败: {exc}")
                progress(
                    "retrying", f"{candidate.source_label}获取失败，正在尝试其他下载源…",
                    source=candidate.source_label, version=candidate.version,
                )

    if not seen_urls:
        raise RuntimeError(
            f"未找到 Chrome {major_version} 对应的 ChromeDriver 下载地址。"
            "\n请手动下载（国内镜像）：https://registry.npmmirror.com/binary.html?path=chrome-for-testing/"
            "\n或官方源：https://googlechromelabs.github.io/chrome-for-testing/"
        )
    raise RuntimeError(f"下载 ChromeDriver 失败: {'; '.join(errors)}")


def get_chrome_version_info() -> str:
    """Get a human-readable Chrome version info string for display."""
    ver = detect_chrome_version()
    if ver:
        return f"Chrome {ver}"
    return "未检测到 Chrome"
