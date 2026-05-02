from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
import os
import platform

from sign_macos_app import verify_app


ROOT = Path(__file__).resolve().parent
APP_NAME = "门窗工具"
BUNDLE_ID = "com.chenshiyue.menchuang.tool"
LOCAL_CODESIGN_IDENTITY = "Menchuang Local Code Signing"
DESKTOP_APP = Path.home() / "Desktop" / f"{APP_NAME}.app"
ENTITLEMENTS = ROOT / "entitlements.plist"


def add_data_args() -> list[str]:
    pairs = [
        ("config.yaml", "."),
        ("static", "static"),
        ("tasks", "tasks"),
        ("data/knowledge_base.json", "data"),
        ("data/learning_queue.json", "data"),
    ]
    args: list[str] = []
    for source, target in pairs:
        source_path = ROOT / source
        if source_path.exists():
            args.extend(["--add-data", f"{source_path}:{target}"])

    tesseract = Path("/opt/homebrew/bin/tesseract")
    # The system Python on this machine is x86_64 while Homebrew tesseract is arm64.
    # Do not force an incompatible OCR binary into the frozen app; the app still
    # runs standalone and uses bundled tessdata when a compatible tesseract is present.
    if tesseract.exists() and platform.machine() == "arm64":
        args.extend(["--add-binary", f"{tesseract}:bin"])
    tessdata_dir = Path("/opt/homebrew/share/tessdata")
    for lang in ("eng.traineddata", "chi_sim.traineddata", "osd.traineddata"):
        lang_path = tessdata_dir / lang
        if lang_path.exists():
            args.extend(["--add-data", f"{lang_path}:tessdata"])
    return args


def build() -> None:
    build_dir = ROOT / "build" / "pyinstaller"
    dist_dir = ROOT / "dist"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(build_dir),
        "--paths",
        str(ROOT / "src"),
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "PIL._tkinter_finder",
        "--hidden-import",
        "Foundation",
        "--hidden-import",
        "Quartz",
        "--hidden-import",
        "Vision",
        "--hidden-import",
        "objc",
        *add_data_args(),
        str(ROOT / "floating_region_assistant.py"),
    ]
    codesign_identity = os.environ.get("MENCHUANG_CODESIGN_IDENTITY", LOCAL_CODESIGN_IDENTITY)
    if codesign_identity:
        command.extend(["--codesign-identity", codesign_identity])
        if ENTITLEMENTS.exists():
            command.extend(["--osx-entitlements-file", str(ENTITLEMENTS)])
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    subprocess.run(command, cwd=str(ROOT), check=True, env=env)

    built_app = dist_dir / f"{APP_NAME}.app"
    if not built_app.exists():
        raise FileNotFoundError(f"PyInstaller did not create {built_app}")
    if DESKTOP_APP.exists():
        shutil.rmtree(DESKTOP_APP)
    shutil.copytree(built_app, DESKTOP_APP)
    verify_app(DESKTOP_APP)
    print(f"已生成独立 App: {DESKTOP_APP}")


if __name__ == "__main__":
    build()
