"""Tests for SettingsView check update UI integration."""

import asyncio
from unittest.mock import AsyncMock, patch
import pytest
import toga

from atbclone import __version__
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


def test_on_check_update_already_latest(toga_app):
    async def _test():
        set_language("zh")
        view = SettingsView()
        view.update_service = AsyncMock()
        view.update_service.check_for_updates.return_value = None

        await view.on_check_update(view.btn_check_update)

        assert t("update_already_latest", ver=__version__) in view.lbl_update_status.text
        assert view.btn_check_update.enabled is True
        set_language(None)

    asyncio.run(_test())


def test_on_check_update_failure(toga_app):
    async def _test():
        view = SettingsView()
        view.update_service = AsyncMock()
        view.update_service.check_for_updates.side_effect = Exception("Network offline")

        await view.on_check_update(view.btn_check_update)

        assert "❌" in view.lbl_update_status.text
        assert "Network offline" in view.lbl_update_status.text
        assert view.btn_check_update.enabled is True

    asyncio.run(_test())
