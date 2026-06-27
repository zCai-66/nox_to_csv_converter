from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "outputs" / "build"
DEPS_DIR = ROOT / "outputs" / "pyinstaller"
HOME_DIR = ROOT / "outputs" / "build_home"
EXE_PATH = ROOT / "nox-to-csv.exe"


def main() -> int:
    env = _ensure_pyinstaller()
    if env is None:
        return 1

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for stale in ROOT.glob("nox-to-csv*.exe"):
        stale.unlink()
    legacy_dist = ROOT / "outputs" / "dist"
    if legacy_dist.exists():
        for stale in legacy_dist.glob("nox-to-csv*.exe"):
            stale.unlink()
    exe_path = _build_exe(env)
    if exe_path is None:
        return 1
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    print(exe_path)
    return 0


def _build_exe(env: dict[str, str]) -> Path | None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "nox-to-csv",
        "--distpath",
        str(ROOT),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT / "src"),
        str(ROOT / "src" / "nox_csv_extractor" / "gui.py"),
    ]
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode != 0:
        return None
    return EXE_PATH


def _ensure_pyinstaller() -> dict[str, str] | None:
    env = os.environ.copy()
    env = _with_build_home(env)
    if importlib.util.find_spec("PyInstaller") is not None:
        return env

    env = _with_local_deps(env)
    if importlib.util.find_spec("PyInstaller") is not None:
        return env

    DEPS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        install = subprocess.run(_pip_install_command(), cwd=ROOT, timeout=180)
    except subprocess.TimeoutExpired:
        print("Timed out installing PyInstaller build dependencies.", file=sys.stderr)
        return None
    if install.returncode != 0:
        print("PyInstaller is required to build the exe.", file=sys.stderr)
        return None

    env = _with_local_deps(_with_build_home(os.environ.copy()))
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller installation completed but cannot be imported.", file=sys.stderr)
        return None
    return env


def _with_local_deps(env: dict[str, str]) -> dict[str, str]:
    if not DEPS_DIR.exists():
        return env
    sys.path.insert(0, str(DEPS_DIR))
    pythonpath = str(DEPS_DIR)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    return env


def _with_build_home(env: dict[str, str]) -> dict[str, str]:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    env["USERPROFILE"] = str(HOME_DIR)
    env["HOME"] = str(HOME_DIR)
    env["HOMEDRIVE"] = str(HOME_DIR.drive)
    env["HOMEPATH"] = str(HOME_DIR.relative_to(HOME_DIR.anchor))
    return env


def _pip_install_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--progress-bar",
        "off",
        "--timeout",
        "30",
        "--retries",
        "2",
        "--target",
        str(DEPS_DIR),
        "--no-deps",
        "pyinstaller==6.21.0",
        "altgraph==0.17.5",
        "pefile==2024.8.26",
        "pywin32-ctypes==0.2.3",
        "pyinstaller-hooks-contrib==2026.6",
        "importlib-metadata==8.7.1",
        "zipp==3.23.0",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
