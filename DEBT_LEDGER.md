main.py God-Object — خطة v3.0 قيد التنفيذ
- FINDING-01 → resolved
- [legacy-debt] test_terminal_node_consent_is_wired::test_consent_callback_is_actually_passed
  يسقط في baseline 6132bd0 (قبل ARCH-6) — دين موروث في core/dag/launcher.py.
  الإصلاح: إضافة consent_callback parameter إلى launch_nabdos_core (ذرة DAG-2).
  لا علاقة له بـ ARCH-6.

- [model-grounding] ORCA-FLASH المحلي يتجاهل قاعدة Tool-first أحياناً
  ويرفض من افتراض («لا أستطيع قراءة…») رغم وجود الأداة.
  القاعدة مُرساة في core/prompts.py للنماذج الأقوى.
  ترشيح مستقبلي: UX-9 صياغة أمرية قصيرة للنماذج الصغيرة،
  أو فرض ميكانيكي في المحرك (إعادة محاولة عند رفضٍ بلا استدعاء أداة).
