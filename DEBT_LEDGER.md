main.py God-Object — خطة v3.0 قيد التنفيذ
- FINDING-01 → resolved
- FINDING-02 → ARCH-7

- [legacy-debt] test_terminal_node_consent_is_wired::test_consent_callback_is_actually_passed
  يسقط في baseline 6132bd0 (قبل ARCH-6) — دين موروث في core/dag/launcher.py.
  الإصلاح: إضافة consent_callback parameter إلى launch_nabdos_core (ذرة DAG-2).
  لا علاقة له بـ ARCH-6.
