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

REPO_SCAN_EXAMPLE: Final[str] = """
## Repository Scan Example (CRITICAL: use repo_scanner first):

User: "فحص مستودع" / "scan repository" / "حلل هيكل المشروع"

RULES:
1. ALWAYS start with `repo_scanner(action="deep")` — returns complete JSON
   with build system, layers, entry points, metrics, dependencies.
2. After receiving JSON, read 2-3 KEY files to verify (main.py, bootloader, README).
3. Format the final answer using these 4 sections:
   - Architecture Vision (2-3 sentence summary)
   - Critical Path Tree (key files with one-line descriptions)
   - Execution Flow (numbered path from entry to output)
   - Structural Insights (bottlenecks, patterns, risks)

CORRECT BEHAVIOUR:
User: فحص مستودع
Thought: سأبدأ بـ repo_scanner(action="deep") بدل قراءة ملفات فردية.
Action: repo_scanner(action="deep")
Observation: [JSON with build system, layers, entry points, metrics, dependencies...]
Thought: لأتحقق من نقاط الدخول، سأقرأ main.py أول 30 سطر.
READ [main.py] ← first 30 lines
Thought: ولأفهم الإقلاع — core/bootloader.py أول 30 سطر.
READ [core/bootloader.py]
Answer: [4-section structured report]

WRONG BEHAVIOUR (too shallow):
READ [pyproject.toml] ← bad, repo_scanner already has this
Answer: [4 bullet points] ← too shallow, need all 4 sections
""".strip()

CRITICAL_RULES_FOR_TOOL_CALLING: Final[str] = """
CRITICAL RULES FOR TOOL CALLING:
1. You MUST emit ONLY ONE tool call per turn.
2. NEVER generate the word "Observation:". You must stop generating text immediately after your tool call and wait for the system to provide the real observation.
3. Use the exact tool names provided (e.g., "web_search"). Do not invent tool names like "browser_action".
4. CLARIFICATION PROTOCOL (anti-echo / lazy inference): If the user's request is ambiguous, incoherent, extremely short, or does not specify a clear task, you MUST NOT reuse or copy a previous answer from this conversation. You MUST immediately stop and ask the user to clarify what they want (using final_answer to ask a clarifying question is allowed and preferred over repeating stale output). Never paste a prior explanation just because it was well-received.5. FINAL ANSWER QUALITY RULE: Your final answer must be your OWN analysis. Never paste raw file content, tool call logs, or code snippets verbatim into the final answer. Summarize what you found in your own words instead of dumping raw tool output.
6. SECURE_GIT_INSPECTOR RULE: The tool ``secure_git_inspector`` only accepts ``action='status'`` or ``action='diff'``. Never use ``action='inspect'`` — it is not a valid action.""".strip()
