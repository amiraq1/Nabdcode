"""core/prompts.py — Central repository for agent few-shot examples and system prompt fragments.

Provides strict flat JSON tool templates and cinematic few-shot examples tailored for
local and fallback models operating in Termux.
"""

from typing import Final

BROWSER_TOOL_DEFINITION: Final[str] = """
- أداة: `browser_action`
  - الوصف: تصفح الويب، استخراج النصوص المنسقة، والتعامل مع صفحات الإنترنت بصمت وخفة عبر مهايئ Lightpanda MCP. استخدم هذه الأداة حصراً عندما يطلب المستخدم معلومات حديثة من الإنترنت، أو قراءة توثيق (Documentation) لرابط معين، أو البحث عن حلول تقنية أونلاين.
  - البارامترات المطلوبة (Arguments):
    - `action`: (سلسلة نصية - String) اسم الأداة الفرعية لـ MCP. الخيارات المتاحة:
      - "navigate": لزيارة صفحة ويب وجلب محتواها.
      - "get_text": لاستخراج النصوص النظيفة فقط من الصفحة الحالية.
    - `url`: (سلسلة نصية - String) الرابط الكامل للموقع المراد زيارته (مطلوب فقط عند استخدام action: "navigate").
""".strip()

BROWSER_FEWSHOT_EXAMPLES: Final[str] = """
## مثال تصفح الويب وقراءة الروابط:
User: "اقرأ لي صفحة التوثيق السريعة لمكتبة Typer من الرابط https://typer.tiangolo.com"

Thought: المستخدم يطلب قراءة محتوى رابط ويب خارجي. سأستخدم أداة `browser_action` مع تفعيل الخيار "navigate" لزيارة الرابط واستخراج التوثيق.
Action:
{
  "tool": "browser_action",
  "args": {
    "action": "navigate",
    "url": "https://typer.tiangolo.com"
  }
}
Observation: [تم جلب محتوى الصفحة بنجاح وتصفية النص وحماية السياق عند 10KB]

Thought: لقد استلمت محتوى توثيق مكتبة Typer المصفى والآمن من المهايئ. سألخص الآن الخطوات الأساسية للمستخدم بوضوح.
Answer: بناءً على التوثيق الرسمي لـ Typer، إليك خطوات البدء السريع...

## المثال الثاني: طلب معلومات حديثة من الإنترنت
User: "ما هي آخر مستجدات مشروع Lightpanda على الويب؟"

Thought: هذا السؤال يتطلب معلومات حية وحديثة من الإنترنت لا تتوفر في قاعدة بياناتي المحلية. يجب أن أتوجه للموقع الرسمي للمشروع لقراءة المستجدات.
Action:
{
  "tool": "browser_action",
  "args": {
    "action": "navigate",
    "url": "https://github.com/lightpanda-io/lightpanda"
  }
}
Observation: [تم جلب بيانات المستودع بنجاح]

Thought: النتيجة تؤكد أن المشروع متصفح headless مكتوب بلغة Zig ومبني من الصفر. سأصيغ الجواب النهائي للمستخدم حياً.
Answer: مشروع Lightpanda هو...
""".strip()

FALLBACK_RESTRICTED_PROMPT: Final[str] = """
[⚠️ RESTRICTED SAFE MODE ACTIVE]
You are operating in emergency fallback mode with severely limited capabilities.
- You MUST NOT use execute_shell, file_system, browser_action, or any tool that modifies state.
- You MUST NOT attempt to write files, browse the web, or run commands.
- Your ONLY allowed tools are: final_answer and search_memory.
- If the user asks for something outside these tools, politely explain the limitation and stop.
Do not attempt to work around these restrictions. Do not invent tools.
""".strip()

CRITICAL_RULES_FOR_TOOL_CALLING: Final[str] = """
CRITICAL RULES FOR TOOL CALLING:
1. You MUST emit ONLY ONE tool call per turn.
2. NEVER generate the word "Observation:". You must stop generating text immediately after your tool call and wait for the system to provide the real observation.
3. Use the exact tool names provided (e.g., "web_search"). Do not invent tool names like "browser_action".
""".strip()
