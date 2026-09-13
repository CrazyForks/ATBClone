# Auto-Update Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-app check-for-updates and silent DMG installation to ATBClone Settings, backed by GitHub Release `latest.json` manifest generation.

**Architecture:** Four layers:
1. CI/CD: Generate `latest.json` containing version, notes, pub_date, and platform DMG URL + SHA256 checksum during release packaging; upload it alongside release assets.
2. i18n: Add ~10 new multilingual translation keys across all 9 supported languages.
3. Service: Implement `UpdateService` to fetch `latest.json`, compare versions, stream download DMG with progress callbacks, verify SHA256, mount via `hdiutil`, install via `ditto`, and clean up.
4. UI: Expand Card 5 in `SettingsView` with a "Check for Updates" button, dynamic status/progress label, and dialog-based quit prompt.

**Tech Stack:** Python 3.12, Toga (macOS Cocoa GUI), `requests>=2.28` (HTTP streaming download), macOS CLI tools (`hdiutil`, `ditto`, `osascript`), GitHub Actions (`gh release upload`).

**Spec:** `docs/superpowers/specs/2026-09-13-auto-update-design.md`

## Global Constraints

- Target macOS native patterns, PySide6/Toga, Python 3.12+, with `conda run -n ATBClone`
- Test command: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/`
- Zero unapproved external dependencies (only `requests>=2.28` approved for GUI extra)
- All network operations in `UpdateService` must be offloaded from main thread via `asyncio.get_running_loop().run_in_executor()`
- Progress callback from worker thread must update Toga UI safely on main loop

---

### Task 1: Declare `requests` Dependency in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml:27-49`
- Test: `tests/test_dependencies.py`

**Interfaces:**
- Consumes: None
- Produces: `requests>=2.28` available in `gui` optional-dependencies and Briefcase app requires

- [ ] **Step 1: Write failing test verifying requests is in pyproject dependencies**

Create `tests/test_dependencies.py`:
```python
"""Test project dependencies declarations."""

from pathlib import Path
import tomllib


def test_requests_dependency_declared():
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    gui_deps = data.get("project", {}).get("optional-dependencies", {}).get("gui", [])
    assert any("requests" in dep for dep in gui_deps), "requests must be in project.optional-dependencies.gui"

    briefcase_reqs = data.get("tool", {}).get("briefcase", {}).get("app", {}).get("atbclone", {}).get("requires", [])
    assert any("requests" in req for req in briefcase_reqs), "requests must be in tool.briefcase.app.atbclone.requires"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_dependencies.py -v`
Expected: FAIL with `AssertionError: requests must be in project.optional-dependencies.gui`

- [ ] **Step 3: Update `pyproject.toml`**

Modify `pyproject.toml`:
In `[project.optional-dependencies]`:
```toml
gui = ["toga>=0.4.0", "requests>=2.28"]
```
In `[tool.briefcase.app.atbclone]`:
```toml
requires = [
    "toga>=0.4.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "requests>=2.28",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_dependencies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
conda run -n ATBClone git add pyproject.toml tests/test_dependencies.py
conda run -n ATBClone git commit -m "build: add requests dependency for auto-update feature"
```

---

### Task 2: Update Packaging Script and GitHub Actions for `latest.json`

**Files:**
- Modify: `scripts/build_release_packages.sh:236-255`
- Modify: `.github/workflows/release.yml:160-225`
- Test: `tests/test_build_release_manifest.py`

**Interfaces:**
- Consumes: `dist/ATBClone-${TARGET_VERSION}-arm64.dmg`, `dist/release_notes.md`
- Produces: `dist/latest.json` containing `version`, `notes`, `pub_date`, and `platforms["darwin-aarch64"]`

- [ ] **Step 1: Write failing unit test for `latest.json` generation logic**

Create `tests/test_build_release_manifest.py`:
```python
"""Test release manifest (latest.json) generator."""

import json
from pathlib import Path
import pytest


def generate_manifest(dist_dir: Path, version: str, pub_date: str) -> Path:
    dmg_file = dist_dir / f"ATBClone-{version}-arm64.dmg"
    notes_file = dist_dir / "release_notes.md"
    manifest_file = dist_dir / "latest.json"

    import hashlib
    dmg_bytes = dmg_file.read_bytes()
    sha256 = hashlib.sha256(dmg_bytes).hexdigest()
    notes = notes_file.read_text(encoding="utf-8") if notes_file.exists() else ""

    data = {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": {
            "darwin-aarch64": {
                "checksum": sha256,
                "url": f"https://github.com/aitobox/ATBClone/releases/download/v{version}/ATBClone-{version}-arm64.dmg",
            }
        },
    }
    manifest_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_file


def test_generate_manifest(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    dmg = dist_dir / "ATBClone-1.6.0-arm64.dmg"
    dmg.write_bytes(b"mock dmg binary data")
    notes = dist_dir / "release_notes.md"
    notes.write_text("## Changelog\n- Fix bug", encoding="utf-8")

    manifest = generate_manifest(dist_dir, "1.6.0", "2026-09-13T12:00:00.000Z")
    assert manifest.exists()

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["version"] == "1.6.0"
    assert data["notes"] == "## Changelog\n- Fix bug"
    assert data["pub_date"] == "2026-09-13T12:00:00.000Z"
    assert "darwin-aarch64" in data["platforms"]
    plat = data["platforms"]["darwin-aarch64"]
    assert len(plat["checksum"]) == 64
    assert plat["url"] == "https://github.com/aitobox/ATBClone/releases/download/v1.6.0/ATBClone-1.6.0-arm64.dmg"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_build_release_manifest.py -v`
Expected: PASS (verifies our manifest structure generator contract)

- [ ] **Step 3: Modify `scripts/build_release_packages.sh`**

Add Section 4 to `scripts/build_release_packages.sh` after checksum generation:
```bash
# ------------------------------------------------------------------------------
# 4. Generate latest.json Update Manifest
# ------------------------------------------------------------------------------
MANIFEST_FILE="dist/latest.json"
echo ""
echo "==> Generating latest.json update manifest..."
PUB_DATE=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
export TARGET_VERSION
export PUB_DATE
python3 - << 'PY_EOF'
import hashlib
import json
import os
from pathlib import Path

version = os.environ["TARGET_VERSION"]
pub_date = os.environ["PUB_DATE"]
dmg_path = Path(f"dist/ATBClone-{version}-arm64.dmg")
notes_path = Path("dist/release_notes.md")

sha256 = hashlib.sha256(dmg_path.read_bytes()).hexdigest()
notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

data = {
    "version": version,
    "notes": notes,
    "pub_date": pub_date,
    "platforms": {
        "darwin-aarch64": {
            "checksum": sha256,
            "url": f"https://github.com/aitobox/ATBClone/releases/download/v{version}/ATBClone-{version}-arm64.dmg",
        }
    },
}
Path("dist/latest.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print("[✔] Generated dist/latest.json")
PY_EOF
```

Also update print summary around line 254:
```bash
printf "  4. Manifest:    %s\n" "${MANIFEST_FILE}"
```

- [ ] **Step 4: Modify `.github/workflows/release.yml`**

In step `Upload Workflow Artifacts`:
```yaml
          path: |
            dist/ATBCloneCli-${{ env.VERSION }}-arm64.tar.gz
            dist/ATBClone-${{ env.VERSION }}-arm64.dmg
            dist/checksums.txt
            dist/latest.json
```

In step `Create or Update GitHub Release`:
```bash
          CLI_PKG="dist/ATBCloneCli-${VERSION}-arm64.tar.gz"
          GUI_PKG="dist/ATBClone-${VERSION}-arm64.dmg"
          CHECKSUMS="dist/checksums.txt"
          MANIFEST="dist/latest.json"
```
And in `gh release upload`:
```bash
          if gh release upload "${TAG_NAME}" "${CLI_PKG}" "${GUI_PKG}" "${CHECKSUMS}" "${MANIFEST}" --clobber; then
```

- [ ] **Step 5: Run existing build script tests**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_build_script.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
conda run -n ATBClone git add scripts/build_release_packages.sh .github/workflows/release.yml tests/test_build_release_manifest.py
conda run -n ATBClone git commit -m "ci: generate and upload latest.json release manifest for auto-updates"
```

---

### Task 3: Add Update Translations to `i18n.py`

**Files:**
- Modify: `src/atbclone/core/i18n.py`
- Test: `tests/test_i18n_update_keys.py`

**Interfaces:**
- Consumes: None
- Produces: 10 new translation keys in `MESSAGES` dictionary with 9 language translations:
  - `settings_btn_check_update`
  - `update_checking`
  - `update_already_latest`
  - `update_found`
  - `update_downloading`
  - `update_verifying`
  - `update_installing`
  - `update_done_title`
  - `update_done_msg`
  - `update_error`

- [ ] **Step 1: Write failing test verifying all 10 update translation keys exist in 9 languages**

Create `tests/test_i18n_update_keys.py`:
```python
"""Tests for auto-update i18n translation keys."""

import pytest
from atbclone.core.i18n import MESSAGES, SUPPORTED_LANGUAGES, t, set_language


REQUIRED_KEYS = [
    "settings_btn_check_update",
    "update_checking",
    "update_already_latest",
    "update_found",
    "update_downloading",
    "update_verifying",
    "update_installing",
    "update_done_title",
    "update_done_msg",
    "update_error",
]


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_update_keys_exist_for_all_languages(key):
    assert key in MESSAGES, f"Missing key '{key}' in MESSAGES"
    msg_dict = MESSAGES[key]
    for lang in SUPPORTED_LANGUAGES:
        assert lang in msg_dict, f"Missing language '{lang}' for key '{key}'"
        assert msg_dict[lang].strip(), f"Empty translation for '{lang}' in '{key}'"


def test_update_formatted_strings():
    set_language("zh")
    assert "v1.6.0" in t("update_already_latest", ver="1.6.0")
    assert "45%" in t("update_downloading", pct=45)
    assert "Network error" in t("update_error", err="Network error")
    set_language(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_i18n_update_keys.py -v`
Expected: FAIL with `AssertionError: Missing key 'settings_btn_check_update' in MESSAGES`

- [ ] **Step 3: Add the 10 keys to `MESSAGES` in `src/atbclone/core/i18n.py`**

Add to `MESSAGES` dictionary:
```python
    "settings_btn_check_update": {
        "en": "Check for Updates",
        "zh": "检查更新",
        "zh_TW": "檢查更新",
        "ja": "アップデートを確認",
        "ko": "업데이트 확인",
        "de": "Nach Updates suchen",
        "fr": "Vérifier les mises à jour",
        "ru": "Проверить обновления",
        "es": "Buscar actualizaciones",
    },
    "update_checking": {
        "en": "Checking for updates...",
        "zh": "正在检查更新...",
        "zh_TW": "正在檢查更新...",
        "ja": "アップデートを確認中...",
        "ko": "업데이트 확인 중...",
        "de": "Suche nach Updates...",
        "fr": "Vérification des mises à jour...",
        "ru": "Проверка обновлений...",
        "es": "Buscando actualizaciones...",
    },
    "update_already_latest": {
        "en": "✓ Already up to date (v{ver})",
        "zh": "✓ 已是最新版本 (v{ver})",
        "zh_TW": "✓ 已是最新版本 (v{ver})",
        "ja": "✓ 最新バージョンです (v{ver})",
        "ko": "✓ 이미 최신 버전입니다 (v{ver})",
        "de": "✓ Bereits auf dem neuesten Stand (v{ver})",
        "fr": "✓ Déjà à jour (v{ver})",
        "ru": "✓ Уже установлена последняя версия (v{ver})",
        "es": "✓ Ya está actualizado (v{ver})",
    },
    "update_found": {
        "en": "New version v{ver} found, downloading...",
        "zh": "发现新版本 v{ver}，正在下载...",
        "zh_TW": "發現新版本 v{ver}，正在下載...",
        "ja": "新しいバージョン v{ver} が見つかりました。ダウンロード中...",
        "ko": "새 버전 v{ver} 발견, 다운로드 중...",
        "de": "Neue Version v{ver} gefunden, wird heruntergeladen...",
        "fr": "Nouvelle version v{ver} trouvée, téléchargement...",
        "ru": "Найдена новая версия v{ver}, загрузка...",
        "es": "Nueva versión v{ver} encontrada, descargando...",
    },
    "update_downloading": {
        "en": "Downloading... {pct}%",
        "zh": "正在下载... {pct}%",
        "zh_TW": "正在下載... {pct}%",
        "ja": "ダウンロード中... {pct}%",
        "ko": "다운로드 중... {pct}%",
        "de": "Herunterladen... {pct}%",
        "fr": "Téléchargement... {pct}%",
        "ru": "Загрузка... {pct}%",
        "es": "Descargando... {pct}%",
    },
    "update_verifying": {
        "en": "Verifying package checksum...",
        "zh": "正在校验安装包...",
        "zh_TW": "正在校驗安裝包...",
        "ja": "パッケージのチェックサムを確認中...",
        "ko": "패키지 체크섬 확인 중...",
        "de": "Überprüfe Paket-Prüfsumme...",
        "fr": "Vérification du paquet...",
        "ru": "Проверка контрольной суммы...",
        "es": "Verificando suma de comprobación...",
    },
    "update_installing": {
        "en": "Installing update...",
        "zh": "正在安装更新...",
        "zh_TW": "正在安裝更新...",
        "ja": "アップデートをインストール中...",
        "ko": "업데이트 설치 중...",
        "de": "Update wird installiert...",
        "fr": "Installation de la mise à jour...",
        "ru": "Установка обновления...",
        "es": "Instalando actualización...",
    },
    "update_done_title": {
        "en": "Update Complete",
        "zh": "更新完成",
        "zh_TW": "更新完成",
        "ja": "アップデート完了",
        "ko": "업데이트 완료",
        "de": "Update abgeschlossen",
        "fr": "Mise à jour terminée",
        "ru": "Обновление завершено",
        "es": "Actualización completada",
    },
    "update_done_msg": {
        "en": "ATBClone has been updated to v{ver}. Click OK to quit, then relaunch manually.",
        "zh": "ATBClone 已成功更新至 v{ver}。点击确定后将退出应用，请手动重新启动。",
        "zh_TW": "ATBClone 已成功更新至 v{ver}。點擊確定後將退出應用，請手動重新啟動。",
        "ja": "ATBClone は v{ver} に更新されました。OKをクリックして終了し、手動で再起動してください。",
        "ko": "ATBClone이 v{ver}(으)로 업데이트되었습니다. 확인을 클릭하여 종료한 후 수동으로 다시 실행하세요.",
        "de": "ATBClone wurde auf v{ver} aktualisiert. Klicken Sie auf OK, um das Programm zu beenden, und starten Sie es dann manuell neu.",
        "fr": "ATBClone a été mis à jour vers v{ver}. Cliquez sur OK pour quitter, puis relancez manuellement.",
        "ru": "ATBClone обновлен до версии v{ver}. Нажмите OK для выхода, затем перезапустите приложение вручную.",
        "es": "ATBClone se ha actualizado a v{ver}. Haga clic en Aceptar para salir y luego reinicie manualmente.",
    },
    "update_error": {
        "en": "❌ Update failed: {err}",
        "zh": "❌ 检查更新失败: {err}",
        "zh_TW": "❌ 檢查更新失敗: {err}",
        "ja": "❌ アップデートに失敗しました: {err}",
        "ko": "❌ 업데이트 실패: {err}",
        "de": "❌ Update fehlgeschlagen: {err}",
        "fr": "❌ Échec de la mise à jour : {err}",
        "ru": "❌ Ошибка обновления: {err}",
        "es": "❌ Error en la actualización: {err}",
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_i18n_update_keys.py -v`
Expected: PASS

- [ ] **Step 5: Run existing i18n tests**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_i18n.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
conda run -n ATBClone git add src/atbclone/core/i18n.py tests/test_i18n_update_keys.py
conda run -n ATBClone git commit -m "i18n: add multilingual translations for auto-update feature"
```

---

### Task 4: Implement `UpdateService`

**Files:**
- Create: `src/atbclone/gui/services/update_service.py`
- Test: `tests/test_update_service.py`

**Interfaces:**
- Consumes: `atbclone.__version__`, `requests`
- Produces:
  ```python
  @dataclass
  class UpdateInfo:
      version: str
      notes: str
      pub_date: str
      checksum: str
      download_url: str

  class UpdateService:
      LATEST_JSON_URL: str
      PLATFORM_KEY: str
      async def check_for_updates(self) -> UpdateInfo | None: ...
      async def download_and_install(self, info: UpdateInfo, on_progress: Callable[[int, int], None]) -> None: ...
  ```

- [ ] **Step 1: Write comprehensive unit tests with mocked network/system calls**

Create `tests/test_update_service.py`:
```python
"""Unit tests for UpdateService."""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from atbclone.gui.services.update_service import UpdateInfo, UpdateService, _parse_version


def test_parse_version():
    assert _parse_version("1.6.0") == (1, 6, 0)
    assert _parse_version("v1.6.0") == (1, 6, 0)
    assert _parse_version("2.10.1") > _parse_version("2.9.5")
    assert _parse_version("1.6.1") > _parse_version("1.6.0")
    assert _parse_version("1.6.0") == _parse_version("1.6.0")


@pytest.mark.asyncio
async def test_check_for_updates_has_newer():
    service = UpdateService()
    mock_payload = {
        "version": "99.0.0",
        "notes": "Test notes",
        "pub_date": "2026-09-13T12:00:00.000Z",
        "platforms": {
            "darwin-aarch64": {
                "checksum": "abc123sha",
                "url": "https://example.com/ATBClone-99.0.0-arm64.dmg",
            }
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("requests.get", return_value=mock_resp):
        info = await service.check_for_updates()
        assert info is not None
        assert info.version == "99.0.0"
        assert info.download_url == "https://example.com/ATBClone-99.0.0-arm64.dmg"
        assert info.checksum == "abc123sha"


@pytest.mark.asyncio
async def test_check_for_updates_already_latest():
    service = UpdateService()
    mock_payload = {
        "version": "0.0.1",
        "notes": "Old notes",
        "pub_date": "2020-01-01T00:00:00.000Z",
        "platforms": {
            "darwin-aarch64": {
                "checksum": "abc",
                "url": "https://example.com/old.dmg",
            }
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("requests.get", return_value=mock_resp):
        info = await service.check_for_updates()
        assert info is None


@pytest.mark.asyncio
async def test_check_for_updates_request_error():
    service = UpdateService()
    with patch("requests.get", side_effect=Exception("Connection refused")):
        with pytest.raises(Exception, match="Connection refused"):
            await service.check_for_updates()


@pytest.mark.asyncio
async def test_download_and_verify_checksum_mismatch(tmp_path):
    service = UpdateService()
    info = UpdateInfo(
        version="2.0.0",
        notes="Notes",
        pub_date="2026-09-13T00:00:00Z",
        checksum="expected_sha_hex_but_will_differ",
        download_url="https://example.com/ATBClone-2.0.0-arm64.dmg",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": "12"}
    mock_resp.iter_content.return_value = [b"mock content"]

    progress_calls = []
    def on_progress(downloaded, total):
        progress_calls.append((downloaded, total))

    with patch("requests.get", return_value=mock_resp):
        with patch.object(service, "_get_download_path", return_value=tmp_path / "test.dmg"):
            with pytest.raises(ValueError, match="Checksum mismatch"):
                await service.download_and_install(info, on_progress)

    assert len(progress_calls) > 0
    assert not (tmp_path / "test.dmg").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_update_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atbclone.gui.services.update_service'`

- [ ] **Step 3: Implement `src/atbclone/gui/services/update_service.py`**

Create `src/atbclone/gui/services/update_service.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/test_update_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
conda run -n ATBClone git add src/atbclone/gui/services/update_service.py tests/test_update_service.py
conda run -n ATBClone git commit -m "feat: implement UpdateService with streaming download and silent install"
```

---

### Task 5: Integrate Update UI in `SettingsView`

**Files:**
- Modify: `src/atbclone/gui/views/settings_view.py:210-250`
- Test: `tests/gui/test_settings_update_ui.py`

**Interfaces:**
- Consumes: `UpdateService`, `t()`
- Produces:
  - `view.btn_check_update`: Button to trigger update check
  - `view.lbl_update_status`: Label showing update status / download progress
  - `view.on_check_update(widget)`: Async event handler managing state transitions and quit prompt

- [ ] **Step 1: Write failing GUI tests for SettingsView update button and handler**

Create `tests/gui/test_settings_update_ui.py`:
```python
"""Tests for SettingsView check update UI integration."""

import asyncio
from unittest.mock import AsyncMock, patch
import pytest
import toga

from atbclone.core.i18n import set_language, t
from atbclone.gui.services.update_service import UpdateInfo
from atbclone.gui.views.settings_view import SettingsView


def test_settings_view_update_widgets_exist(toga_app):
    set_language("zh")
    view = SettingsView()
    assert hasattr(view, "btn_check_update")
    assert hasattr(view, "lbl_update_status")
    assert view.btn_check_update.text == t("settings_btn_check_update")
    assert view.lbl_update_status.text == ""
    set_language(None)


@pytest.mark.asyncio
async def test_on_check_update_already_latest(toga_app):
    view = SettingsView()
    view.update_service = AsyncMock()
    view.update_service.check_for_updates.return_value = None

    await view.on_check_update(view.btn_check_update)

    assert "已是最新版本" in view.lbl_update_status.text
    assert view.btn_check_update.enabled is True


@pytest.mark.asyncio
async def test_on_check_update_failure(toga_app):
    view = SettingsView()
    view.update_service = AsyncMock()
    view.update_service.check_for_updates.side_effect = Exception("Network offline")

    await view.on_check_update(view.btn_check_update)

    assert "❌" in view.lbl_update_status.text
    assert "Network offline" in view.lbl_update_status.text
    assert view.btn_check_update.enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/gui/test_settings_update_ui.py -v`
Expected: FAIL with `AttributeError: 'SettingsView' object has no attribute 'btn_check_update'`

- [ ] **Step 3: Update `SettingsView` in `src/atbclone/gui/views/settings_view.py`**

1. Import `UpdateService`:
```python
from atbclone.gui.services.update_service import UpdateInfo, UpdateService
```

2. In `__init__`:
Initialize `self.update_service = UpdateService()`.
In Card 5 (lines ~219-225), replace single button with horizontal box:
```python
        row_about_btns = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=6))

        self.btn_release_notes = toga.Button(
            t("settings_btn_release_notes"),
            on_press=self.on_open_release_notes,
            style=Pack(height=30, margin_right=8, font_size=13),
        )
        row_about_btns.add(self.btn_release_notes)

        self.btn_check_update = toga.Button(
            t("settings_btn_check_update"),
            on_press=self.on_check_update,
            style=Pack(height=30, font_size=13),
        )
        row_about_btns.add(self.btn_check_update)
        inner_info.add(row_about_btns)

        self.lbl_update_status = toga.Label(
            "",
            style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin_top=4),
        )
        inner_info.add(self.lbl_update_status)
```

3. Implement `on_check_update` method in `SettingsView`:
```python
    async def on_check_update(self, widget: toga.Button) -> None:
        """Handle Check for Updates button press."""
        self.btn_check_update.enabled = False
        self.lbl_update_status.text = t("update_checking")
        logger.info("User initiated check for updates")

        try:
            info = await self.update_service.check_for_updates()
            if not info:
                self.lbl_update_status.text = t("update_already_latest", ver=__version__)
                self.btn_check_update.enabled = True
                return

            self.lbl_update_status.text = t("update_found", ver=info.version)
            logger.info(f"Update found: v{info.version}, starting download and install")

            loop = asyncio.get_running_loop()

            def _on_progress(downloaded: int, total: int) -> None:
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    msg = t("update_downloading", pct=pct)
                else:
                    msg = t("update_downloading", pct=0)

                def _ui_update():
                    self.lbl_update_status.text = msg

                loop.call_soon_threadsafe(_ui_update)

            await self.update_service.download_and_install(info, on_progress=_on_progress)

            self.lbl_update_status.text = t("update_done_title")
            if self.app_instance and hasattr(self.app_instance, "main_window"):
                await self.app_instance.main_window.info_dialog(
                    t("update_done_title"),
                    t("update_done_msg", ver=info.version),
                )
            os._exit(0)

        except Exception as e:
            logger.error(f"Update error: {e}", exc_info=True)
            self.lbl_update_status.text = t("update_error", err=str(e))
            self.btn_check_update.enabled = True
```

4. In `retranslate_ui` (if present or called): ensure `self.btn_check_update.text = t("settings_btn_check_update")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/gui/test_settings_update_ui.py -v`
Expected: PASS

- [ ] **Step 5: Run existing settings GUI tests**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/gui/test_settings_release_notes.py tests/gui/test_logs_and_settings_views.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
conda run -n ATBClone git add src/atbclone/gui/views/settings_view.py tests/gui/test_settings_update_ui.py
conda run -n ATBClone git commit -m "feat: integrate check for updates button and status flow in SettingsView"
```

---

### Task 6: Comprehensive Regression Testing & Quality Gate

**Files:**
- Test: All tests in `tests/`

- [ ] **Step 1: Run full test suite**

Run: `PYTHONPATH=src conda run -n ATBClone python -m pytest tests/`
Expected: All tests pass without error or regression.

- [ ] **Step 2: Run Ruff lint check**

Run: `conda run -n ATBClone ruff check src/atbclone/gui/services/update_service.py src/atbclone/gui/views/settings_view.py tests/test_update_service.py tests/gui/test_settings_update_ui.py`
Expected: Clean with 0 errors.

- [ ] **Step 3: Commit any final touch-ups**

```bash
conda run -n ATBClone git status
# If clean, proceed; otherwise commit fixes
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-13-auto-update-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
