"""7z archive extraction wrapper."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_7z(configured: str = "") -> str:
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("7z.exe") or shutil.which("7z")
    if found:
        return found
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    candidates = [
        base / "7z.exe",
        base / "bash" / "compiled" / "7z.exe",
        base.parent / "bash" / "compiled" / "7z.exe",
        base.parent.parent / "bash" / "compiled" / "7z.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def extract(archive_path: str, dest_dir: str, seven_zip_path: str = "") -> None:
    """Extract archive to dest_dir using 7z. Raises RuntimeError on failure."""
    exe = _find_7z(seven_zip_path)
    if not exe:
        raise RuntimeError(
            "7z.exe not found — set 7-Zip path in Settings or install 7-Zip and add to PATH"
        )
    os.makedirs(dest_dir, exist_ok=True)
    result = subprocess.run(
        [exe, "x", archive_path, "-y", f"-o{dest_dir}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"7z extraction failed:\n{result.stdout}\n{result.stderr}")
