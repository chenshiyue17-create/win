from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path


APP_NAME = "门窗工具"
DEFAULT_BUNDLE_ID = "com.chenshiyue.menchuang.tool"
LOCAL_CODESIGN_IDENTITY = "Menchuang Local Code Signing"
DEFAULT_APP = Path.home() / "Desktop" / f"{APP_NAME}.app"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        message = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(message or f"Command failed: {' '.join(command)}")
    return result


def app_bundle_id(app_path: Path) -> str:
    info_path = app_path / "Contents" / "Info.plist"
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    return str(info.get("CFBundleIdentifier") or info.get("CFBundleName") or APP_NAME)


def sign_app(app_path: Path, identity: str) -> None:
    if not app_path.exists():
        raise FileNotFoundError(f"App not found: {app_path}")
    if identity == "-":
        # PyInstaller already ad-hoc signs the bundle during BUNDLE creation.
        # Re-signing the collected app with --deep can misclassify Python
        # metadata directories in Contents/Frameworks as invalid bundles.
        verify_app(app_path)
        return
    run(
        [
            "codesign",
            "--force",
            "--timestamp",
            "--options",
            "runtime",
            "--sign",
            identity,
            str(app_path),
        ]
    )


def verify_app(app_path: Path) -> str:
    run(["codesign", "--verify", "--deep", "--ignore-resources", "--verbose=2", str(app_path)])
    details = run(["codesign", "-dv", "--verbose=4", str(app_path)]).stderr
    return details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sign and verify the macOS 门窗工具.app bundle.")
    parser.add_argument("--app", type=Path, default=DEFAULT_APP, help="Path to the .app bundle.")
    parser.add_argument(
        "--identity",
        default=LOCAL_CODESIGN_IDENTITY,
        help='Signing identity. Use "Menchuang Local Code Signing" locally, "-" for ad-hoc, or a Developer ID Application certificate name.',
    )
    parser.add_argument("--verify-only", action="store_true", help="Only verify the existing signature.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.verify_only:
        sign_app(args.app, args.identity)
    details = verify_app(args.app)
    print(f"App: {args.app}")
    print(f"Bundle ID: {app_bundle_id(args.app)}")
    print("Signature verified.")
    for line in details.splitlines():
        if line.startswith(("Authority=", "TeamIdentifier=", "Signature=", "Identifier=", "CodeDirectory")):
            print(line)


if __name__ == "__main__":
    main()
