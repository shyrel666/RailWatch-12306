"""The pinned interpreter and the dependency lock must agree with the files that declare them."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_FILES = ("requirements.txt", "requirements-build.txt")


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned_python():
    return ".".join(read(".python-version").strip().split(".")[:2])


def direct_requirements():
    """(name, exact version or None) for each requirement in the lock's input files."""
    found = []
    for name in INPUT_FILES:
        for line in read(name).splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            match = re.match(r"^([A-Za-z0-9_.-]+)\s*(?:==\s*([^\s;]+))?", line)
            found.append((normalized(match.group(1)), match.group(2)))
    return found


def locked_packages():
    """name -> [version, number of hashes] from requirements.lock."""
    locked = {}
    current = None
    for line in read("requirements.lock").splitlines():
        entry = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if entry:
            current = normalized(entry.group(1))
            locked[current] = [entry.group(2), 0]
        elif current and line.startswith(" ") and "--hash=" in line:
            locked[current][1] += 1
    return locked


class DependencyLockTests(unittest.TestCase):
    def test_lock_covers_every_direct_requirement_at_its_pinned_version(self):
        locked = locked_packages()
        direct = direct_requirements()
        self.assertTrue(direct, "未能从 requirements.txt / requirements-build.txt 读到依赖")
        for name, version in direct:
            self.assertIn(name, locked, f"{name} 不在 requirements.lock 中，请重新生成锁文件")
            if version:
                self.assertEqual(locked[name][0], version, f"{name} 的锁定版本与声明不一致，请重新生成锁文件")

    def test_every_locked_package_carries_a_hash(self):
        locked = locked_packages()
        self.assertTrue(locked, "requirements.lock 中没有任何锁定的包")
        missing = sorted(name for name, (_version, hashes) in locked.items() if hashes == 0)
        self.assertEqual(missing, [], "这些包没有哈希，pip --require-hashes 会拒绝安装")

    def test_lock_was_resolved_for_the_pinned_python(self):
        header = "\n".join(read("requirements.lock").splitlines()[:3])
        self.assertIn(f"--python-version {pinned_python()}", header,
                      "requirements.lock 不是按 .python-version 的版本生成的，请重新生成")


class PinnedPythonTests(unittest.TestCase):
    def test_project_metadata_names_the_pinned_python(self):
        pin = pinned_python()
        self.assertRegex(pin, r"^3\.\d+$")
        project = read("pyproject.toml")
        self.assertIn(f'requires-python = ">={pin}"', project)
        declared = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', project)
        self.assertEqual(declared, [pin], "classifiers 应只声明 .python-version 中的版本")

    def test_runtime_spec_refuses_other_interpreters(self):
        spec = read("RailWatch_runtime.spec")
        self.assertIn('os.path.join(SPECPATH, ".python-version")', spec)
        self.assertIn("raise SystemExit(", spec.split("hiddenimports = ")[0],
                      "版本检查必须在收集依赖之前执行")


if __name__ == "__main__":
    unittest.main()
