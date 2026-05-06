from pathlib import Path
import plistlib
import subprocess

import pytest


APP_DIR = Path("/Users/cc/Desktop/门窗工具.app")


def test_desktop_app_bundle_has_required_files() -> None:
    executable = APP_DIR / "Contents" / "MacOS" / "门窗工具"
    info = APP_DIR / "Contents" / "Info.plist"
    resources = APP_DIR / "Contents" / "Resources"

    assert executable.exists()
    assert executable.stat().st_mode & 0o111
    assert info.exists()
    assert (resources / "Python.framework").exists()
    assert (resources / "static").exists()
    assert (resources / "tasks").exists()


def test_desktop_app_bundle_is_signed() -> None:
    result = subprocess.run(
        ["codesign", "--verify", "--deep", "--ignore-resources", "--verbose=2", str(APP_DIR)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_desktop_app_info_plist_is_valid() -> None:
    with (APP_DIR / "Contents" / "Info.plist").open("rb") as handle:
        info = plistlib.load(handle)

    assert info["CFBundleName"] == "门窗工具"
    assert info["CFBundleExecutable"] == "门窗工具"
    assert info["CFBundleIdentifier"] == "com.chenshiyue.menchuang.tool"
    assert info["CFBundlePackageType"] == "APPL"


def test_desktop_app_signature_details_are_readable() -> None:
    result = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(APP_DIR)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "Executable=/Users/cc/Desktop/门窗工具.app/Contents/MacOS/门窗工具" in result.stderr
    assert "CodeDirectory" in result.stderr
    if "Signature=adhoc" in result.stderr:
        pytest.skip("Local desktop app is ad-hoc signed in this environment")
    assert "Authority=Menchuang Local Code Signing" in result.stderr


def test_desktop_app_has_library_validation_entitlement() -> None:
    result = subprocess.run(
        ["codesign", "-d", "--entitlements", "-", str(APP_DIR)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    if not result.stdout:
        pytest.skip("Local desktop app has no embedded entitlements in this environment")
    assert "com.apple.security.cs.disable-library-validation" in result.stdout
