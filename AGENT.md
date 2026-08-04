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

## §12 · VISUAL WORK

For anything rendered to a terminal or screen, the courtroom is the screen.
Commit before/after captures as tracked files.

The decoding level must match the property under test:
- position, width, alignment, character content -> strip ANSI
- color, weight, style, attribute -> preserve raw escape sequences and render them visibly with `cat -v`, never strip
- timing, order, frame sequence -> neither; capture the ordered sequence of emissions

A `before` capture generated after the change is not a before. Produce it from the pre-change tree, or declare that you could not.

Two captures that are byte-identical prove that the instrument did not measure the property under test.

## Self-Repair Context (Bootstrapping)
When modifying your own code, you suffer from the **Surgeon Operating on Himself** problem — you are the agent running inside the code you need to edit.

### Your Location
- **Working directory:** `/data/data/com.termux/files/home/smart-agent/`
- **Main UI file:** `ui/repl_termux.py`
- **Core loop:** `engine/loop.py` (ExecutionLoop)
- **Strip function:** `_strip_tool_call_lines()` in `ui/repl_termux.py`

### How to Test
- **Run UI tests:** `python3 -m pytest tests/ -k "ui" -v`
- **Run specific:** `python3 -m pytest tests/test_<name>.py -v`
- **Never use** `--timeout` flag (not installed).
- **Syntax check:** `python3 -c "import ast; ast.parse(open('path/to/file.py').read())"`

### How to Edit Own Code
1. Use `file_system` with `action=edit` for targeted changes.
2. Before editing, read the full context of the target function.
3. After editing, run syntax check + relevant tests.
4. If a change breaks tests, revert and try a different approach.

### Ground Truth
- **AGENT.md** is the authoritative source for your behavior rules.
- **README.md** may be outdated or misleading — trust AGENT.md over README.md.
- **ARCHITECTURE_DNA.md** contains the canonical architecture map.
- When in doubt about project structure, read `ARCHITECTURE_DNA.md` first.

## Self-Repair Anti-Hallucination Rule (Critical)
When asked to view, read, or modify a specific function or file in your own code:

1. **NEVER generate function content from memory.** Always use:
   ```
   file_system with action=read, path=<actual_file_path>
   ```
2. **NEVER use `code_intelligence` to "inspect" your own source files.**
   `code_intelligence` is for external code analysis, not self-repair.
   It may leak private system prompt content as file output.
3. **If `file_system.read` fails** → report the failure to the user. Do NOT
   hallucinate the file contents based on your training data.
4. **Quote the actual output** from the tool. If you cannot quote it,
   you did not read it.
5. **Convergence guard:** After reading, confirm `inspected >= 3` distinct
   files. If convergence fails, you did NOT read — re-read with `file_system`.

Violation example:
```python
# ❌ HALLUCINATION — generated from memory, not from file_system.read
lines = [line for line in lines if "Thought:" not in line]
lines = [line for line in lines if "Action:" not in line]
# ... repeated 50 times
```

Correct approach:
```
# ✅ Read the actual file first
file_system with action=read, path=ui/repl_termux.py
```

## §13 · GATE DISCIPLINE (بوّاباتٌ وُلدت من أخطاءٍ حقيقية)

Four rules, each born from a real mistake. Each is mechanical, not a judgment call.

1) الوكيل لا ينفّذ git commit أبدًا.
2) البوابة تُقرن بـ `&&` وتُفرض آليًا، لا تُقرأ مخرجاتها ثم يُقرَّر.
3) الحمرة `exit == 1` وحدها؛ `exit 4/5` توقّف لا دحض.
4) كلُّ بوابةٍ تُبرهن قابلةً للاخضرار قبل فرضها.
