"""
Automated Windows build script for Online Subtitle Translator.
Builds the PyInstaller distribution and optionally deploys to local Utility folder.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
SPEC_FILE = ROOT_DIR / "packaging" / "OnlineSubtitleTranslator.spec"

# Local deployment directory (optional)
_deploy_override = os.environ.get("DEPLOY_DIR")
if _deploy_override:
    UTILITY_DEST = Path(_deploy_override)
else:
    # Explicit user utility path: C:\Ali\Utility\Online Subtitle Translator
    _canonical_utility = Path(r"C:\Ali\Utility\Online Subtitle Translator")
    if _canonical_utility.parent.exists():
        UTILITY_DEST = _canonical_utility
    else:
        UTILITY_DEST = Path.home() / "Utility" / "Online Subtitle Translator"


def build():
    print("=" * 60)
    print("Building Online Subtitle Translator Windows Executable...")
    print("=" * 60)

    # 1. Clean previous build artifacts
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR, ignore_errors=True)
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    # 2. Run PyInstaller
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC_FILE)
    ]
    print(f"Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(ROOT_DIR))
    if res.returncode != 0:
        print("PyInstaller build failed!")
        sys.exit(1)

    built_app_dir = DIST_DIR / "Online Subtitle Translator"
    if not built_app_dir.exists():
        print(f"Build output not found at: {built_app_dir}")
        sys.exit(1)

    print(f"Build succeeded at: {built_app_dir}")

    # Add portable flag
    (built_app_dir / "portable.txt").write_text("Online Subtitle Translator Portable Mode Enabled\n", encoding="utf-8")

    # Copy assets directory directly beside executable
    assets_src = ROOT_DIR / "assets"
    if assets_src.exists():
        dest_assets = built_app_dir / "assets"
        if dest_assets.exists():
            shutil.rmtree(dest_assets, ignore_errors=True)
        shutil.copytree(assets_src, dest_assets)

    # Copy docs and licenses
    for doc in ["README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md"]:
        src = ROOT_DIR / doc
        if src.exists():
            shutil.copy2(src, built_app_dir / doc)

    # 3. Deploy to local utility folder if configured / present
    if UTILITY_DEST and UTILITY_DEST.parent.exists():
        try:
            print(f"\nDeploying to User Utility directory: {UTILITY_DEST}...")
            UTILITY_DEST.mkdir(parents=True, exist_ok=True)
            for item in built_app_dir.iterdir():
                dest = UTILITY_DEST / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            exe_path = UTILITY_DEST / "Online Subtitle Translator.exe"
            print(f"Deployment complete! Executable is ready at:\n{exe_path}")
        except Exception as e:
            print(f"Note: Local utility deployment skipped ({e}). Build in dist is ready.")
    else:
        print("\nNote: Local utility deployment skipped (no local utility directory). Build in dist is ready.")


if __name__ == "__main__":
    build()
