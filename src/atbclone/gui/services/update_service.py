"""Update Service for checking and installing ATBClone updates from GitHub Releases."""

import asyncio
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Optional
import requests

from atbclone import __version__
from atbclone.core.logger import get_logger

logger = get_logger("gui.update_service")


@dataclass
class UpdateInfo:
    version: str
    notes: str
    pub_date: str
    checksum: str
    download_url: str


def _parse_version(v: str) -> tuple[int, ...]:
    cleaned = v.strip().lstrip("v")
    parts = []
    for x in cleaned.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class UpdateService:
    LATEST_JSON_URL = "https://github.com/aitobox/ATBClone/releases/latest/download/latest.json"
    PLATFORM_KEY = "darwin-aarch64"
    MOUNT_POINT = Path("/tmp/atbclone_update_mnt")
    TARGET_APP_PATH = Path("/Applications/ATBClone.app")

    def _get_download_path(self, version: str) -> Path:
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        return downloads_dir / f"ATBClone-{version}-arm64.dmg"

    async def check_for_updates(self) -> Optional[UpdateInfo]:
        """Fetch latest.json and return UpdateInfo if remote is strictly newer than current version."""
        loop = asyncio.get_running_loop()

        def _fetch():
            logger.info(f"Checking for updates from {self.LATEST_JSON_URL}...")
            resp = requests.get(self.LATEST_JSON_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            remote_ver_str = data.get("version", "").strip()
            remote_ver = _parse_version(remote_ver_str)
            curr_ver = _parse_version(__version__)

            logger.info(f"Version check: current={__version__} ({curr_ver}), remote={remote_ver_str} ({remote_ver})")
            if remote_ver > curr_ver:
                platform_info = data.get("platforms", {}).get(self.PLATFORM_KEY, {})
                download_url = platform_info.get("url", "")
                checksum = platform_info.get("checksum", "").strip()

                if not download_url or not checksum:
                    raise ValueError(f"Missing download URL or checksum for platform '{self.PLATFORM_KEY}'")

                return UpdateInfo(
                    version=remote_ver_str,
                    notes=data.get("notes", ""),
                    pub_date=data.get("pub_date", ""),
                    checksum=checksum,
                    download_url=download_url,
                )
            return None

        return await loop.run_in_executor(None, _fetch)

    async def download_and_install(
        self,
        info: UpdateInfo,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Download DMG, verify checksum, mount, ditto install to /Applications, detach, and cleanup."""
        loop = asyncio.get_running_loop()

        def _worker():
            dmg_path = self._get_download_path(info.version)
            logger.info(f"Downloading update from {info.download_url} to {dmg_path}...")

            # 1. Streaming Download
            try:
                with requests.get(info.download_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get("content-length", 0))
                    downloaded = 0

                    with open(dmg_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if on_progress:
                                    on_progress(downloaded, total_size)

                # 2. SHA256 Verification
                logger.info("Verifying SHA256 checksum...")
                hasher = hashlib.sha256()
                with open(dmg_path, "rb") as f:
                    while True:
                        block = f.read(65536)
                        if not block:
                            break
                        hasher.update(block)
                computed_sha = hasher.hexdigest()

                if computed_sha.lower() != info.checksum.lower():
                    logger.error(f"SHA256 mismatch! Expected {info.checksum}, got {computed_sha}")
                    if dmg_path.exists():
                        dmg_path.unlink(missing_ok=True)
                    raise ValueError(f"Checksum mismatch! Expected {info.checksum}, got {computed_sha}")

                # 3. Mount DMG
                logger.info(f"Attaching disk image at {self.MOUNT_POINT}...")
                if self.MOUNT_POINT.exists():
                    subprocess.run(["hdiutil", "detach", str(self.MOUNT_POINT), "-force"], capture_output=True)
                self.MOUNT_POINT.mkdir(parents=True, exist_ok=True)

                attach_res = subprocess.run(
                    ["hdiutil", "attach", str(dmg_path), "-nobrowse", "-mountpoint", str(self.MOUNT_POINT)],
                    capture_output=True,
                    text=True,
                )
                if attach_res.returncode != 0:
                    raise RuntimeError(f"Failed to mount DMG: {attach_res.stderr.strip()}")

                try:
                    # 4. Locate .app inside mount point
                    apps = list(self.MOUNT_POINT.glob("*.app"))
                    if not apps:
                        raise RuntimeError(f"No .app bundle found inside {self.MOUNT_POINT}")
                    src_app = apps[0]
                    logger.info(f"Found source app in DMG: {src_app}")

                    # 5. Move existing /Applications/ATBClone.app to Trash
                    if self.TARGET_APP_PATH.exists():
                        logger.info(f"Moving {self.TARGET_APP_PATH} to Trash via osascript...")
                        script = f'tell application "Finder" to move POSIX file "{self.TARGET_APP_PATH}" to trash'
                        trash_res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
                        if trash_res.returncode != 0:
                            logger.warning(f"osascript trash failed ({trash_res.stderr.strip()}), falling back to direct removal")
                            shutil.rmtree(self.TARGET_APP_PATH, ignore_errors=True)

                    # 6. Ditto install new .app
                    logger.info(f"Installing {src_app} to {self.TARGET_APP_PATH} via ditto...")
                    ditto_res = subprocess.run(
                        ["ditto", str(src_app), str(self.TARGET_APP_PATH)],
                        capture_output=True,
                        text=True,
                    )
                    if ditto_res.returncode != 0:
                        raise RuntimeError(f"Failed to ditto install application: {ditto_res.stderr.strip()}")

                    logger.info("Successfully installed update to /Applications/ATBClone.app")
                finally:
                    # 7. Detach mount
                    logger.info("Detaching disk image...")
                    subprocess.run(["hdiutil", "detach", str(self.MOUNT_POINT), "-force"], capture_output=True)

            finally:
                # 8. Cleanup temporary DMG
                if dmg_path.exists():
                    try:
                        dmg_path.unlink()
                        logger.info("Removed temporary DMG")
                    except Exception as e:
                        logger.warning(f"Failed to remove temp DMG: {e}")

        await loop.run_in_executor(None, _worker)
