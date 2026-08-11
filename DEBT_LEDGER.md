main.py God-Object — خطة v3.0 قيد التنفيذ
- FINDING-01 → resolved
- [legacy-debt] DAG-2 → resolved

- [x] [model-grounding] resolved: UX-10 فرض ميكانيكي (retry loop)

- [x] [tools-bus-import] tools/file_system.py يستورد core.kernel.events.bus
  مباشرة — خرق طبقي جديد (اكتُشف 2026-08-11).
  الأدوات يجب أن تكون معزولة عن kernel؛ تمرير الأحداث عبر engine adapter.
  ذرة تنظيف مستقبلية: TOOLS-1.
  - [x] TOOLS-2 → resolved (phase 1)
