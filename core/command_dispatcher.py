import sys
from pathlib import Path
from typing import Any

def validate_fix_path(filepath: str) -> bool:
    """Return True if filepath is safe, False otherwise."""
    from core.kernel.security import get_workspace_root
    try:
        workspace_root = get_workspace_root()
        resolved_target = (workspace_root / filepath).resolve()
        resolved_target.relative_to(workspace_root)
        return True
    except (ValueError, OSError):
        return False

def _cmd_clear(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    state.clear_context()
    state.set_messages([{"role": "system", "content": base_inst}])
    if hasattr(ctx.evidence_log, "clear"):
        ctx.evidence_log.clear()
    elif isinstance(ctx.evidence_log, list):
        ctx.evidence_log.clear()
    if hasattr(ctx.todo_manager, "clear"):
        ctx.todo_manager.clear()
    from core.accept_edits_state import reset_session
    reset_session()
    try:
        import main
        from core.kernel.security import get_workspace_root
        workspace_dir = get_workspace_root()
        checkpoint_file = workspace_dir / main.CHECKPOINT_FILENAME
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            ctx.logger.info("Workspace checkpoint cleared.")
    except Exception as e:
        ctx.logger.warning(f"Failed to unlink checkpoint: {e}")
    sys.stdout.write("\n\033[92m✨ [System] Context and history have been cleared. Ready for a new task!\033[0m\n\n")
    sys.stdout.flush()
    return True

def _cmd_undo(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    parts = user_input.split(maxsplit=1)
    undo_path = parts[1].strip() if len(parts) > 1 else ""
    if not undo_path:
        sys.stdout.write("\n\033[91m⚠ Usage: /undo <filepath>\033[0m\n\n")
    else:
        sys.stdout.write(f"\n{ctx.snapshot_engine.undo(undo_path)}\n\n")
    sys.stdout.flush()
    return True

def _cmd_scan(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    from core.repo_scanner import SECURE_REPO_SCANNER
    from core.kernel.security import get_workspace_root
    from core.ui_bridge import get_bridge
    try:
        scan_data = SECURE_REPO_SCANNER()._deep_scan(get_workspace_root())
        bridge = get_bridge()
        if bridge and hasattr(bridge, "render_scan_result"):
            bridge.render_scan_result(scan_data)
        else:
            total_f = scan_data.get("total_files", len(scan_data.get("files", [])))
            sys.stdout.write(f"\n[Scan] Found {total_f} files in workspace.\n\n")
    except Exception as _scan_exc:
        sys.stdout.write(f"\n\033[91m⚠ deep scan failed: {_scan_exc}\033[0m\n\n")
    sys.stdout.flush()
    return True


def _cmd_refactor(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    parts = user_input.split()
    is_resume = user_input.lower().startswith(("/resume", "nabd resume"))
    target_files_list = parts[1:] if len(parts) > 1 and not is_resume else ["target_dummy.py"]
    try:
        from llm_router import get_secure_model
        from tools.secure_tools import SecureGraphifyTool
        from core.dag.launcher import launch_nabdos_core
        from engine.consent import ConsentManager
        from core.kernel.security import get_workspace_root
        
        llm = get_secure_model()
        ws = str(get_workspace_root())
        graphify = SecureGraphifyTool(workspace_dir=ws)
        taste_rules = ["All functions MUST have strict Type Hints.", "Use clear docstrings and comments."]
        consent_manager = ConsentManager()
        consent_callback = lambda t, a: consent_manager.confirm(
            t, a, evidence_log=ctx.evidence_log, step=getattr(state, "step_count", 0)
        ) is None
        launch_nabdos_core(
            llm_engine=llm,
            graphify_tool=graphify,
            workspace_dir=ws,
            target_files=target_files_list,
            taste_rules=taste_rules,
            resume=is_resume,
            consent_callback=consent_callback,
        )
    except Exception as dag_err:
        sys.stdout.write(f"\n\033[91m❌ [DAG Launcher Error] {dag_err}\033[0m\n\n")
    sys.stdout.flush()
    return True

def _cmd_fix(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    import ast as _ast
    import re as _re
    import subprocess as _sp

    remainder = user_input[len("/fix"):].strip()
    _m = _re.match(r'(.+?)\s*(?:->|→)\s*(.+)', remainder)
    if not _m:
        sys.stdout.write(
            "\n\033[91m⚠ Usage: /fix <filepath> → <function_name>\033[0m\n\n"
        )
        sys.stdout.flush()
        return True

    filepath = _m.group(1).strip()
    func_name = _m.group(2).strip()

    try:
        if not validate_fix_path(filepath):
            sys.stdout.write("\n\033[91m⚠ Error: path outside workspace\033[0m\n\n")
            sys.stdout.flush()
            return True

        target = Path(filepath)
        if not target.exists():
            sys.stdout.write(f"\n\033[91m⚠ File not found: {filepath}\033[0m\n\n")
            sys.stdout.flush()
            return True

        content = target.read_text(encoding="utf-8")
        tree = _ast.parse(content, filename=filepath)

        found = None
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == func_name:
                found = node
                break

        if not found:
            sys.stdout.write(
                f"\n\033[91m⚠ Function '{func_name}' not found in {filepath}\033[0m\n\n"
            )
            sys.stdout.flush()
            return True

        lines = content.splitlines()
        start = found.lineno - 1
        end = getattr(found, "end_lineno", len(lines))
        func_lines = lines[start:end]

        sys.stdout.write(
            f"\n\033[94m📄 {filepath} — function: {func_name}"
            f" (L{found.lineno}-{end})\033[0m\n"
        )
        sys.stdout.write(f"\033[90m{'─' * 60}\033[0m\n")
        for i, line in enumerate(func_lines, start=found.lineno):
            sys.stdout.write(f"\033[2m{i:4d}│\033[0m {line}\n")
        sys.stdout.write(f"\033[90m{'─' * 60}\033[0m\n")
        sys.stdout.flush()

        sys.stdout.write("\n\033[94m🧪 Running ui tests...\033[0m\n")
        sys.stdout.flush()
        result = _sp.run(
            ["python3", "-m", "pytest", "tests/", "-k", "ui", "-v"],
            cwd=str(Path.cwd()),
            capture_output=True, text=True, timeout=60,
        )
        sys.stdout.write(result.stdout + "\n")
        if result.stderr:
            sys.stdout.write(f"\033[91m{result.stderr}\033[0m\n")
        if result.returncode == 0:
            sys.stdout.write("\033[92m✅ All tests passed!\033[0m\n\n")
        else:
            sys.stdout.write(
                f"\033[91m❌ Tests failed (exit code {result.returncode})"
                " — fix the function above, then re-run /fix\033[0m\n\n"
            )
        sys.stdout.flush()

    except SyntaxError as exc:
        sys.stdout.write(f"\n\033[91m⚠ Syntax error in {filepath}: {exc}\033[0m\n\n")
        sys.stdout.flush()
    except _sp.TimeoutExpired:
        sys.stdout.write("\n\033[91m⚠ Tests timed out after 60s\033[0m\n\n")
        sys.stdout.flush()
    except Exception as exc:
        sys.stdout.write(f"\n\033[91m⚠ Error: {exc}\033[0m\n\n")
        sys.stdout.flush()

    return True

def _cmd_expand(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    parts = user_input.split(maxsplit=1)
    cid_arg = parts[1].strip() if len(parts) > 1 else ""
    from core.kernel.collapse import CollapseStore, collapse_store
    if not cid_arg:
        ids = collapse_store.ids()
        if not ids:
            sys.stdout.write("\n\033[2m(no collapsed blocks to expand)\033[0m\n\n")
        else:
            sys.stdout.write(f"\n\033[2mCollapsed blocks: {', '.join(str(i) for i in ids)} — /expand <id>\033[0m\n\n")
        sys.stdout.flush()
        return True
    try:
        cid = int(cid_arg)
    except ValueError:
        sys.stdout.write(f"\n\033[91m⚠ /expand expects a numeric id, got '{cid_arg}'\033[0m\n\n")
        sys.stdout.flush()
        return True
    block = collapse_store.expand(cid)
    if block is None:
        sys.stdout.write(f"\n\033[91m⚠ No collapsed block with id {cid}\033[0m\n\n")
        sys.stdout.flush()
        return True
    sys.stdout.write(f"\n{'─' * 40}\n")
    for line in block:
        sys.stdout.write(f"  {line}\n")
    sys.stdout.flush()
    return True

def _print_plan_status(state: Any) -> None:
    from core.plan_apply import plan_status

    snapshot = plan_status(state)
    mode = str(snapshot["mode"]).upper()
    revision = int(snapshot["revision"])
    items = list(snapshot["items"])
    approved = bool(snapshot["apply_authorized"])
    review_status = snapshot.get("review_status", "not_run")
    review_approved = bool(snapshot.get("review_approved", False))
    sys.stdout.write(
        f"\n[Plan/Apply] mode={mode}; revision={revision}; "
        f"apply_authorized={approved}; review={review_status}; review_approved={review_approved}\n"
    )
    if items:
        for index, item in enumerate(items, start=1):
            sys.stdout.write(f"  {index}. {item}\n")
    else:
        sys.stdout.write("  (no recorded plan)\n")
    sys.stdout.flush()


def _cmd_plan(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    """Enter explicit read-only planning or display the current plan record."""
    from core.plan_apply import (
        PLAN_MODE_INSTRUCTION,
        enter_plan_mode,
        return_to_normal_mode,
        synchronize_mode_context,
    )

    option = user_input[len("/plan"):].strip().lower()
    if option in {"status", "show"}:
        _print_plan_status(state)
        return True
    if option in {"off", "normal", "exit"}:
        return_to_normal_mode(state)
        synchronize_mode_context(state, None)
        sys.stdout.write("\n[Plan/Apply] Returned to NORMAL mode.\n")
        sys.stdout.flush()
        return True

    enter_plan_mode(state)
    synchronize_mode_context(state, PLAN_MODE_INSTRUCTION)
    sys.stdout.write(
        "\n[Plan/Apply] PLAN mode active. Workspace exploration is read-only. "
        "Ask the agent to inspect and record a TODO plan; run /apply only after review.\n"
    )
    sys.stdout.flush()
    return True


def _cmd_apply(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    """Authorize the currently recorded plan revision for gated execution."""
    from core.plan_apply import APPLY_MODE_INSTRUCTION, authorize_apply, synchronize_mode_context

    ok, message = authorize_apply(state)
    if not ok:
        sys.stdout.write(f"\n[Plan/Apply] APPLY refused: {message}\n")
        sys.stdout.flush()
        return True

    synchronize_mode_context(state, APPLY_MODE_INSTRUCTION)
    sys.stdout.write(f"\n[Plan/Apply] {message} Existing consent and edit gates remain active.\n")
    sys.stdout.flush()
    return True


def _cmd_mode(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    _print_plan_status(state)
    return True


def _cmd_tasks(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    """Display the current Task Graph; this command is intentionally read-only."""
    graph = getattr(state, "task_graph", None)
    if graph is None:
        sys.stdout.write("\n[Tasks] No Task Graph exists for the current plan revision.\n")
        sys.stdout.flush()
        return True

    snapshot = graph.to_dict()
    sys.stdout.write(
        f"\n[Tasks] plan_revision={snapshot['plan_revision']} "
        f"count={len(snapshot['tasks'])}\n"
    )
    if not snapshot["tasks"]:
        sys.stdout.write("  (no graph nodes recorded)\n")
    else:
        for task in snapshot["tasks"]:
            deps = ", ".join(task["depends_on"]) or "-"
            sys.stdout.write(
                f"  {task['task_id']}: status={task['status']} "
                f"role={task['role']} depends_on={deps}\n"
            )
    sys.stdout.flush()
    return True


def _cmd_review(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    """Show, run, or approve the diff/test review for the current plan."""
    from core.diff_review import (
        approve_review,
        build_review,
        format_review,
        run_review_tests,
        store_review,
    )
    from core.kernel.security import get_workspace_root

    option = user_input[len("/review"):].strip().lower()
    if option in {"approve", "accept"}:
        ok, message = approve_review(state)
        sys.stdout.write(f"\n[Review] {message}\n")
    elif option in {"run", "check", "tests"}:
        report = run_review_tests(build_review(state, get_workspace_root()), get_workspace_root())
        store_review(state, report)
        sys.stdout.write(f"\n{format_review(report)}\n")
    else:
        report = dict(getattr(state, "review_report", {}) or {})
        if int(report.get("revision", 0) or 0) != int(getattr(state, "plan_revision", 0) or 0):
            report = build_review(state, get_workspace_root())
            store_review(state, report)
        sys.stdout.write(f"\n{format_review(report)}\n")
    sys.stdout.flush()
    return True


COMMANDS = {
    "clear": _cmd_clear, "/clear": _cmd_clear, "/reset": _cmd_clear, "/c": _cmd_clear,
    "/undo": _cmd_undo,
    "فحص": _cmd_scan, "فحص مستودع": _cmd_scan, "scan": _cmd_scan, "scan repo": _cmd_scan, "/deep-scan": _cmd_scan,
    "/refactor": _cmd_refactor, "nabd refactor": _cmd_refactor, "/dag": _cmd_refactor, "/resume": _cmd_refactor, "nabd resume": _cmd_refactor,
    "/fix": _cmd_fix,
    "/expand": _cmd_expand,
    "/plan": _cmd_plan,
    "/apply": _cmd_apply,
    "/mode": _cmd_mode,
    "/tasks": _cmd_tasks,
    "/review": _cmd_review,
}

def process_slash_command(user_input: str, state: Any, ctx: Any, base_inst: str) -> bool:
    lowered = user_input.lower()
    stripped = user_input.strip()
    
    if lowered in COMMANDS:
        return COMMANDS[lowered](user_input, state, ctx, base_inst)
        
    if stripped in COMMANDS:
        return COMMANDS[stripped](user_input, state, ctx, base_inst)
        
    for prefix in (
        "/undo", "/refactor", "nabd refactor", "/dag", "/resume",
        "nabd resume", "/fix", "/expand", "/plan", "/apply", "/mode", "/tasks", "/review",
    ):
        if lowered.startswith(prefix):
            return COMMANDS[prefix](user_input, state, ctx, base_inst)
            
    return False
