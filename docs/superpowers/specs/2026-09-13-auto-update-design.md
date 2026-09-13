# Auto-Update Subsystem Design

**Date:** 2026-09-13  
**Status:** Approved  
**Feature:** 检查更新 / Check for Updates

## Overview

Add an in-app "Check for Updates" feature to the Settings view. When triggered, the app fetches a `latest.json` manifest from GitHub Releases, compares the remote version against the running version, and—if a newer version exists—downloads the DMG, verifies its SHA256 checksum, silently installs it by replacing `/Applications/ATBClone.app`, then prompts the user to quit and relaunch manually.

This requires changes across four layers: CI/CD (manifest generation), service layer (update logic), i18n (new string keys), and UI (Settings card expansion).

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│         Layer 4: UI (settings_view.py)          │
│    "检查更新"按钮 + 状态标签 + 进度标签          │
├─────────────────────────────────────────────────┤
│       Layer 3: Service (update_service.py)      │
│  fetch → compare → download → verify →          │
│  mount → ditto → unmount → prompt exit          │
├─────────────────────────────────────────────────┤
│         Layer 2: i18n (i18n.py)                 │
│          ~10 new multilingual keys               │
├─────────────────────────────────────────────────┤
│     Layer 1: CI/CD (release.yml + build.sh)     │
│   generate latest.json, upload to Release        │
└─────────────────────────────────────────────────┘
```

---

## Layer 1: CI/CD Changes

### scripts/build_release_packages.sh

After the existing SHA256 checksum step (section 3), add a new **section 4** that generates `dist/latest.json` using an inline Python script:

- Reads `dist/release_notes.md` for the `notes` field
- Computes SHA256 of the final DMG with hashlib
- Constructs the GitHub download URL from TARGET_VERSION
- Captures `pub_date` from `date -u +"%Y-%m-%dT%H:%M:%S.000Z"` in shell, passes via env var
- Writes `dist/latest.json` (UTF-8, indent=2)

### .github/workflows/release.yml

Two targeted changes:

1. **Upload Workflow Artifacts step**: add `dist/latest.json` to the `path:` list.
2. **`gh release upload` command**: add `"dist/latest.json"` to the asset list (`--clobber`).

After upload, GitHub exposes the stable URL:
```
https://github.com/aitobox/ATBClone/releases/latest/download/latest.json
```

The existing `checksums.txt` is kept intact.

---

## Layer 2: i18n Changes

### src/atbclone/core/i18n.py

Add ~10 keys to `MESSAGES` with full 9-language coverage (`en`, `zh`, `zh_TW`, `ja`, `ko`, `de`, `fr`, `ru`, `es`):

| Key | zh | en |
|-----|----|----|
| `settings_btn_check_update` | 检查更新 | Check for Updates |
| `update_checking` | 正在检查更新… | Checking for updates… |
| `update_already_latest` | ✓ 已是最新版本（v{ver}） | ✓ Already up to date (v{ver}) |
| `update_found` | 发现新版本 v{ver}，正在下载… | New version v{ver} found, downloading… |
| `update_downloading` | 正在下载… {pct}% | Downloading… {pct}% |
| `update_verifying` | 正在校验文件… | Verifying file… |
| `update_installing` | 正在安装… | Installing… |
| `update_done_title` | 安装完成 | Update Complete |
| `update_done_msg` | ATBClone 已更新至 v{ver}，点击确定后将退出，请手动重新启动。 | ATBClone has been updated to v{ver}. Click OK to quit, then relaunch manually. |
| `update_error` | ❌ 检查失败：{err} | ❌ Update failed: {err} |

---

## Layer 3: Service Layer

### New file: src/atbclone/gui/services/update_service.py

**Data model:**

```python
@dataclass
class UpdateInfo:
    version: str      # "1.7.0"
    notes: str        # release notes markdown
    pub_date: str     # ISO 8601
    checksum: str     # SHA256 hex of DMG
    download_url: str # DMG download URL
```

**Public API:**

```python
class UpdateService:
    LATEST_JSON_URL = (
        "https://github.com/aitobox/ATBClone/releases/latest/download/latest.json"
    )
    PLATFORM_KEY = "darwin-aarch64"

    async def check_for_updates(self) -> UpdateInfo | None:
        """Fetches latest.json in executor. Returns UpdateInfo if newer, None if up to date."""

    async def download_and_install(
        self,
        info: UpdateInfo,
        on_progress: Callable[[int, int], None],  # (downloaded_bytes, total_bytes)
    ) -> None:
        """Streams DMG, verifies SHA256, runs install sequence in executor."""
```

**Version comparison** (zero extra deps):

```python
def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().lstrip("v").split("."))
```

**Installation sequence** (runs in `loop.run_in_executor(None, ...)`, all blocking):

1. Stream-download DMG → `~/Downloads/ATBClone-<ver>-arm64.dmg`
   (requests.get stream=True, chunk_size=65536, call on_progress per chunk)
2. SHA256 verify → raise `ValueError("Checksum mismatch")` on failure, delete DMG
3. `hdiutil attach <dmg> -nobrowse -mountpoint /tmp/atbclone_update_mnt`
4. Locate `ATBClone.app` inside mount point (glob `*.app`)
5. Move `/Applications/ATBClone.app` to Trash via `osascript` (skip if absent)
6. `ditto /tmp/atbclone_update_mnt/ATBClone.app /Applications/ATBClone.app`
7. `hdiutil detach /tmp/atbclone_update_mnt -force`
8. Delete `~/Downloads/ATBClone-<ver>-arm64.dmg`
9. Return normally → UI shows dialog and calls `os._exit(0)`

**Error handling:**

- Network error → propagate `requests.RequestException` → UI shows `update_error`
- SHA256 mismatch → `ValueError` → UI shows `update_error`; temp DMG deleted
- `hdiutil`/`ditto` failure → `RuntimeError(stderr)` → UI shows `update_error`
- `/Applications/ATBClone.app` absent → skip Trash step, proceed with install

**Dependency additions** in `pyproject.toml`:

```toml
# optional-dependencies
gui = ["toga>=0.4.0", "requests>=2.28"]

# briefcase app requires
requires = ["toga>=0.4.0", "pydantic>=2.0", "pyyaml>=6.0", "requests>=2.28"]
```

---

## Layer 4: UI Changes

### src/atbclone/gui/views/settings_view.py

**Card 5 (System Info) — layout addition:**

```
[ ATBClone v1.6.0            ]
[ Python 3.12.x (arm64)      ]
[ macOS 15.x                 ]

[ 查看更新日志 ]  [ 检查更新 ]    ← same row (ROW box)
  正在下载… 45%                   ← lbl_update_status below, shown dynamically
```

**State machine:**

| State | `btn_check_update` | `lbl_update_status` |
|-------|--------------------|---------------------|
| Idle | enabled | `""` (empty/hidden) |
| Checking | disabled | `t("update_checking")` |
| Up to date | re-enabled after 3 s | `t("update_already_latest", ver=...)` |
| Downloading | disabled | `t("update_downloading", pct=N)` |
| Verifying | disabled | `t("update_verifying")` |
| Installing | disabled | `t("update_installing")` |
| Done | — | triggers `info_dialog` → `os._exit(0)` |
| Error | re-enabled | `t("update_error", err=...)` |

**Progress bridge** — `on_progress` fires from executor thread; use
`app.loop.call_soon_threadsafe(lambda: setattr(lbl, "text", ...))` to marshal
label updates back to the main thread safely.

---

## Verification Plan

### Automated Tests

New file `tests/test_update_service.py` (unit, no real network):

- `check_for_updates()` returns `None` when remote == current version
- `check_for_updates()` returns `UpdateInfo` when remote > current
- `check_for_updates()` raises on HTTP 404 / connection error
- `_parse_version()` edge cases: `"v1.0.0"`, `"2.10.0" > "2.9.0"`
- SHA256 mismatch raises `ValueError`
- All network calls mocked via `unittest.mock.patch("requests.get")`

```bash
PYTHONPATH=src conda run -n ATBClone python -m pytest tests/
```

### Manual Verification

1. Launch: `PYTHONPATH=src conda run -n ATBClone python -m atbclone.gui`
2. Open Settings → Card 5 → click "检查更新"
3. Observe state label transitions
4. Use a patched `LATEST_JSON_URL` pointing to a local server with a higher version to exercise full flow
5. After a real tag push, verify `latest.json` appears at the stable GitHub `/latest/download/` URL
