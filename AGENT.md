# AGENT.md - دستور العميل
## القواعد الذهبية
1. المحادثة العادية مثل iraq, مرحبا, كيفك لا تحتاج أدوات.
2. أي سؤال فيه how many / كم عدد = استدع file_system.read أولا ثم عد من المخرجات واقتبسها.
3. ممنوع الادعاء الرقمي بدون backticks من ناتج الأداة.

## أدواتك المتاحة
- file_system.read(path)
- shell(cmd)
- evidence_log.verify()

## الدروس المستفادة تلقائيا 2026-07-10
- أي ادعاء رقمي يجب أن يقتبس الدليل حرفيا بين backticks
- عد الأنماط = اقرأ الملف ثم عد re.compile من المخرجات

## TODO Discipline (Mandatory)
When working on a multi-step task, you MUST use the `todo_write` tool:
1. Before starting, call `todo_write(action="plan", items=[...])`.
2. Before starting a step, call `todo_write(action="update", item_id=N, status="in_progress")`.
3. Before marking a step done, you MUST pass a verification_note quoting command output.
4. If verification fails, do NOT mark done. Keep as in_progress or report failure explicitly.

## Security Compliance Policy
SECURITY COMPLIANCE RULE: If a tool execution fails with a "security validation error" or a whitelist rejection, do not attempt to bypass it or invoke semantic memory for a workaround. Inform the user directly that the command is restricted by the secure execution policy.

## Language & Communication Policy (Mandatory)
- Every visible response MUST be written exclusively in fluent, professional English.
- Treat Arabic solely as an input language. Never generate Arabic text unless explicitly requested by the user.
- All explanations, code, comments, logs, status messages, plans, reports, TODOs, commit messages, documentation, and examples MUST be in English.

## Graphify Knowledge Graph
For any question about this repo's architecture, structure, components, or how to add/modify/find code, your first action MUST be `graphify_tool` with action="query" and target="<question>" when graphify-out/graph.json exists.

Triggers: "how do I…", "where is…", "what does … do", "add/modify a ", "explain the architecture", or anything that depends on how files or classes relate.

Rules:
1. Use action="query" and target="<question>" for general structure discovery.
2. Use action="path" for relationships between <A> and <B>.
3. Use action="explain" for focused concepts.
These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
4. If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
5. Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
6. Only read source files when (a) modifying/debugging specific code, (b) the graph lacks the needed detail, or (c) the graph is missing or stale.
7. After modifying code, run `graphify_tool` with action="update" to keep the graph current (AST-only, no API cost).


