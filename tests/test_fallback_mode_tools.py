"""
حكم R-UI-1: إصلاح Tool Filtering في Fallback Mode.

يوثق أن fallback mode يُزيل execute_shell و file_system من القائمة
المسموح بها. هذا الاختبار يولد أحمراً قبل التعديل (execute_shell و
file_system مفقودان) وخضراءً بعده.
"""

import importlib
import pytest


@pytest.fixture(scope="module")
def loop_helpers():
    return importlib.import_module("engine._loop_helpers")


def test_fallback_mode_includes_execute_shell(loop_helpers):
    """ع1 — execute_shell يجب أن يكون في FALLBACK_ALLOWED_TOOLS."""
    assert "execute_shell" in loop_helpers.FALLBACK_ALLOWED_TOOLS


def test_fallback_mode_includes_file_system(loop_helpers):
    """ع2 — file_system يجب أن يكون في FALLBACK_ALLOWED_TOOLS."""
    assert "file_system" in loop_helpers.FALLBACK_ALLOWED_TOOLS


def test_fallback_mode_still_restricted(loop_helpers):
    """ع3 — الأدوات الخطيرة لا يجب أن تكون في FALLBACK_ALLOWED_TOOLS."""
    dangerous = {"browser_action", "python_repl"}
    forbidden = dangerous & set(loop_helpers.FALLBACK_ALLOWED_TOOLS)
    assert forbidden == set(), f"أدوات خطيرة مسموح بها غير مقصودة: {forbidden}"
