"""Bounded browser cleanup and staged local-data reset. Never sweep by process name."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

from railwatch_preferences import atomic_write_json
from railwatch_state import APP_SLUG

PENDING_FILE = ".cleanup-pending.json"
ELECTRON_USER_DATA_DIR = "electron"


def checked_data_path(directory):
    target = Path(os.path.abspath(directory))
    if target.name != APP_SLUG or os.path.normcase(os.path.realpath(target)) != os.path.normcase(str(target)):
        raise RuntimeError("拒绝清除异常数据目录，请在系统设置中核对数据路径。")
    return target


def checked_backup_path(target, directory):
    backup = Path(os.path.abspath(directory))
    if (backup.parent != target.parent or not re.fullmatch(r"\." + re.escape(APP_SLUG) + r"-clearing-[0-9a-f]{32}", backup.name)
            or os.path.normcase(os.path.realpath(backup)) != os.path.normcase(str(backup))):
        raise RuntimeError("旧数据清理路径异常，已停止清理，请核对数据目录。")
    return backup


WINDOWS_CLEANUP = r'''
$ErrorActionPreference = 'Stop'
$all = @(Get-CimInstance Win32_Process)
$byId = @{}
foreach ($entry in $all) { $byId[[int]$entry.ProcessId] = $entry }
$profile = [regex]::Escape($env:RAILWATCH_CLEANUP_PROFILE.Replace('\', '/'))
$pattern = '(?:^|\s)(?:"--user-data-dir=' + $profile + '"|--user-data-dir="' + $profile + '"|--user-data-dir=' + $profile + ')(?=\s|$)'
$drivers = @($all | Where-Object { $_.Name -eq 'chromedriver.exe' -and $_.ExecutablePath -and
    $_.ExecutablePath.Replace('\', '/') -eq $env:RAILWATCH_CLEANUP_DRIVER.Replace('\', '/') })
$browsers = @($all | Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -and
    $_.CommandLine.Replace('\', '/') -match $pattern })
$roots = @($drivers) + @($browsers)
$rootIds = @($roots | ForEach-Object { [int]$_.ProcessId })
# A different live runtime may own this same directory. Do not terminate it.
foreach ($entry in $roots) {
    $parent = $byId[[int]$entry.ParentProcessId]
    if ($parent -and $parent.CreationDate -le $entry.CreationDate -and
        [int]$parent.ProcessId -ne [int]$env:RAILWATCH_CLEANUP_OWNER -and
        $rootIds -notcontains [int]$parent.ProcessId -and
        [int]$entry.ProcessId -ne [int]$env:RAILWATCH_CLEANUP_OWNED_DRIVER) {
        Write-Output 'OTHER_OWNER'
        exit 2
    }
}
$targets = @{}
foreach ($entry in $roots) { $targets[[int]$entry.ProcessId] = $entry }
# Include only Chrome children of these identified application processes.
do {
    $added = $false
    foreach ($entry in $all) {
        if ($entry.Name -eq 'chrome.exe' -and $targets.ContainsKey([int]$entry.ParentProcessId) -and
            -not $targets.ContainsKey([int]$entry.ProcessId) -and
            $targets[[int]$entry.ParentProcessId].CreationDate -le $entry.CreationDate) {
            $targets[[int]$entry.ProcessId] = $entry
            $added = $true
        }
    }
} while ($added)
foreach ($entry in $targets.Values) {
    $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $entry.ProcessId)
    # Compare identity again before terminating, so a reused PID is not killed.
    if ($current -and $current.CreationDate -eq $entry.CreationDate) {
        Stop-Process -Id $entry.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
$deadline = [DateTime]::UtcNow.AddSeconds(5)
do {
    $remaining = @()
    foreach ($entry in $targets.Values) {
        $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $entry.ProcessId)
        if ($current -and $current.CreationDate -eq $entry.CreationDate) { $remaining += $current }
    }
    if ($remaining.Count -eq 0) { Write-Output 'OK'; exit 0 }
    Start-Sleep -Milliseconds 100
} while ([DateTime]::UtcNow -lt $deadline)
Write-Output 'STILL_RUNNING'
exit 3
'''


def release_orphan_browsers(directory, owned_driver_pid=0):
    target = checked_data_path(directory)
    if sys.platform != "win32":
        return  # The active Selenium session is closed by the bridge on all platforms.
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_CLEANUP],
                                capture_output=True, text=True, timeout=25,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                env={**os.environ, "RAILWATCH_CLEANUP_PROFILE": str(target / "chrome_profile_12306"),
                                     "RAILWATCH_CLEANUP_DRIVER": str(target / "chromedriver.exe"),
                                     "RAILWATCH_CLEANUP_OWNER": str(os.getpid()),
                                     "RAILWATCH_CLEANUP_OWNED_DRIVER": str(owned_driver_pid or 0)})
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("无法完成浏览器占用检查，尚未删除数据。请退出其他 RailWatch 实例后重试。") from exc
    if result.returncode == 2 and "OTHER_OWNER" in result.stdout:
        raise RuntimeError("另一个仍在运行的程序正在使用 RailWatch 浏览器，尚未删除数据。请退出其他实例后重试。")
    if result.returncode != 0 or result.stdout.strip() != "OK":
        raise RuntimeError("受控浏览器或驱动尚未退出，尚未删除数据。请关闭相关会话后重试。")


def _is_reparse_or_symlink(path):
    if path.is_symlink():
        return True
    st = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and getattr(st, "st_file_attributes", 0) & reparse_flag)


def _has_electron_subdir(target):
    electron_dir = target / ELECTRON_USER_DATA_DIR
    if not (electron_dir.exists() or electron_dir.is_symlink()):
        return False
    if _is_reparse_or_symlink(electron_dir):
        raise RuntimeError("数据目录包含链接或联接，尚未删除数据。请先检查这些路径。")
    return electron_dir.is_dir()


def check_files_released(target):
    """Probe DELETE sharing before moving anything; do not change file contents."""
    if sys.platform != "win32":
        return
    import win32con
    import win32file
    import pywintypes
    for root, dirs, files in os.walk(target, followlinks=False):
        root_path = Path(root)
        # Electron holds open Chromium handles in data_dir/electron during runtime resets;
        # session/cache cleanup inside that directory is coordinated by the main process.
        if root_path == target and ELECTRON_USER_DATA_DIR in dirs:
            electron_dir = root_path / ELECTRON_USER_DATA_DIR
            if _is_reparse_or_symlink(electron_dir):
                raise RuntimeError("数据目录包含链接或联接，尚未删除数据。请先检查这些路径。")
            dirs.remove(ELECTRON_USER_DATA_DIR)
        for name in dirs + files:
            path = root_path / name
            if _is_reparse_or_symlink(path):
                raise RuntimeError("数据目录包含链接或联接，尚未删除数据。请先检查这些路径。")
            try:
                handle = win32file.CreateFile(str(path), win32con.DELETE,
                                             win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                                             None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
                handle.Close()
            except (OSError, pywintypes.error) as exc:
                raise RuntimeError(f"文件仍被占用或无删除权限：{path.relative_to(target)}。尚未删除数据，请关闭相关程序后重试。") from exc


def _remove_tree(path):
    def writable_retry(function, filename, _error):
        # Only remove readonly flags on descendants of the already checked tree.
        resolved = os.path.realpath(filename)
        if os.path.normcase(os.path.commonpath((str(path), resolved))) != os.path.normcase(str(path)):
            raise RuntimeError("拒绝清除数据目录之外的文件。")
        os.chmod(filename, stat.S_IWRITE | stat.S_IREAD)
        function(filename)
    shutil.rmtree(path, onerror=writable_retry)


def _move_siblings_to_backup(target, backup):
    children = [entry for entry in target.iterdir() if entry.name != ELECTRON_USER_DATA_DIR]
    if not children:
        return []
    backup.mkdir(exist_ok=True)
    moved_names = []
    try:
        for entry in children:
            os.replace(str(entry), str(backup / entry.name))
            moved_names.append(entry.name)
    except OSError as exc:
        for name in reversed(moved_names):
            try:
                os.replace(str(backup / name), str(target / name))
            except OSError:
                pass
        try:
            backup.rmdir()
        except OSError:
            pass
        raise RuntimeError("数据目录仍被占用或无修改权限，尚未删除数据。请退出其他实例后重试。") from exc
    return moved_names


def _rollback_siblings(target, backup, moved_names):
    for entry in list(target.iterdir()):
        if entry.name == ELECTRON_USER_DATA_DIR:
            continue
        if entry.is_dir() and not _is_reparse_or_symlink(entry):
            _remove_tree(entry)
        else:
            entry.unlink(missing_ok=True)
    for name in moved_names:
        os.replace(str(backup / name), str(target / name))
    try:
        backup.rmdir()
    except OSError:
        pass


def reset_directory(directory, initialize):
    """Switch to a fresh store before disposal; retain and report undeleted old files."""
    target = checked_data_path(directory)
    pending = []
    manifest = target.parent / f".{APP_SLUG}{PENDING_FILE}"
    for record in (manifest, target / PENDING_FILE):  # Also honor the previous on-disk format.
        if record.exists():
            try:
                entries = json.loads(record.read_text(encoding="utf-8"))
                if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
                    raise ValueError("invalid cleanup paths")
                pending.extend(checked_backup_path(target, entry) for entry in entries)
            except (OSError, ValueError) as exc:
                raise RuntimeError("旧数据清理记录无法读取，尚未删除数据。请检查数据目录。") from exc
    pending = list(dict.fromkeys(pending))
    prior_pending = list(pending)
    preserve_electron = _has_electron_subdir(target)
    check_files_released(target)
    backup = checked_backup_path(target, target.parent / f".{APP_SLUG}-clearing-{uuid.uuid4().hex}")
    pending.append(backup)

    def sync_manifest(paths):
        try:
            if paths:
                atomic_write_json(str(manifest), [str(path) for path in paths])
            else:
                manifest.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        atomic_write_json(str(manifest), [str(path) for path in pending])
        if os.name == "posix":
            parent_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    except OSError as exc:
        raise RuntimeError("无法保存清理记录，尚未删除数据。请检查磁盘空间与目录权限。") from exc
    moved_names = []
    moved = False
    if preserve_electron:
        try:
            moved_names = _move_siblings_to_backup(target, backup)
        except Exception:
            if not backup.exists():
                sync_manifest(prior_pending)
            raise
        if moved_names:
            moved = True
    elif target.exists():
        try:
            os.replace(target, backup)
        except OSError as exc:
            if not backup.exists():
                sync_manifest(prior_pending)
            raise RuntimeError("数据目录仍被占用或无修改权限，尚未删除数据。请退出其他实例后重试。") from exc
        moved = True
    try:
        target.mkdir(exist_ok=True)
        initialized = initialize()
    except Exception as exc:
        try:
            if preserve_electron:
                _rollback_siblings(target, backup, moved_names)
            else:
                if target.exists():
                    _remove_tree(checked_data_path(target))
                if moved:
                    os.replace(backup, target)
        except Exception as rollback:
            raise RuntimeError(f"初始化失败且无法恢复目录；旧数据保留在 {backup}，请先恢复后再使用。") from rollback
        if not backup.exists():
            sync_manifest(prior_pending)
        raise RuntimeError("新数据目录初始化失败，已恢复原数据，请检查磁盘空间与目录权限。") from exc
    remaining = []
    for path in pending:
        checked_backup_path(target, path)
        for attempt in range(3):
            try:
                if path.exists():
                    _remove_tree(path)
                break
            except (OSError, RuntimeError):
                if attempt == 2:
                    remaining.append(str(path))
                else:
                    time.sleep(0.15)
    # Keep the recovery manifest updated until every old directory is gone.
    # A later clear will retry it, including after a crash during disposal.
    sync_manifest(remaining)
    return initialized, remaining
