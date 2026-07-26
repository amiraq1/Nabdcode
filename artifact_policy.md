# Artifact Policy — Session C.1

> **Date:** 2026-07-26
> **Status:** Adopted
> **Scope:** Classification rule for all files in the repository for release/commit decisions.

---

## A. Included in Release / Commits

Only the following categories may be committed:

| Category | Description | Examples from current tree |
|:---------|:------------|:---------------------------|
| **Source code (new)** | New `.py` files in `core/`, `engine/`, `tools/`, `ui/` | `core/turn_outcome.py`, `core/convergence_gate.py`, `engine/_dispatch.py` |
| **Source code (modified)** | Changes to existing `.py` files in source directories | `core/app_context.py`, `engine/loop.py`, `main.py` |
| **Tests (new)** | New test files in `tests/` | `tests/test_gate_l1_loop_semantics.py`, `tests/test_convergence_gate.py` |
| **Tests (modified)** | Changes to existing test files | `tests/test_phase5_harden.py`, `tests/test_sanitize.py` |
| **Test infrastructure** | `conftest.py`, `__init__.py` in test dirs | `tests/conftest.py`, `tests/__init__.py` |
| **Required documentation** | AGENT.md, README.md, MEMORY.md, etc. | `AGENT.md` (self-repair rules) |
| **Build/CI config** | `pyproject.toml`, `.pre-commit-config.yaml`, `requirements.txt` | `pyproject.toml` |

**Rule:** A file must be **actively maintained source code, test code, or configuration** to be included. Generated or transient outputs are excluded by default.

---

## B. Excluded from Release / Commits

The following categories are **permanently excluded** unless explicitly reviewed and promoted:

| Category | Rationale | Current files |
|:---------|:----------|:--------------|
| **Gate artifacts** | Generated during deferred-prompt-loop gate verification; not source code | `l6_behavioral_evidence_matrix.md`, `l7_baseline_regression_report.md`, `l8_closure_report.md`, `loop_v3_unauthorized_change_incident.md` |
| **Evidence matrices** | Subset of gate artifacts; detailed evidence tables | `l6_behavioral_evidence_matrix.md` |
| **Regression/closure reports** | Subset of gate artifacts; baseline comparisons | `l7_baseline_regression_report.md`, `l8_closure_report.md` |
| **Forensics reports** | Auto-generated DNA analysis snapshots; transient | `forensics_report*.md` (10 files) |
| **Scratch/fix scripts** | One-off debugging, path fixing, AST updates | `fix_*.py` (4 files), `scratch_*.py`, `update_l1_ast.py`, `build_litert_rag.py` |
| **Temp debug scripts** | Ad-hoc experiments, not part of product | `debug_agent.py`, `test_script.py`, `test_openai.py` |
| **Test dispatcher/dag** | Manual test runner experiments | `test_dispatcher.py`, `run_dag_test.py` |
| **JSON data dumps** | Transient AST dumps, collection outputs | `ast_out.json`, `dna_report.json`, `tests_collection.txt` |
| **Test output captures** | `report.txt`, `report.txt23` | Captured pytest output; transient |
| **Runtime state** | Per-run agent memory, DBs, semantic index | `agent_memory.json`, `workspace_memory.db`, `workspace_semantic_memory.json`, `STATE.md` |
| **Recovery/backup bundles** | Pre-refactor backups, phase recovery patches | `.recovery_bundle/`, `.phase2_backup/`, `.phase22a_recovery/` |
| **Build artifacts** | Bytecode, egg-info, dist | `__pycache__/`, `*.pyc`, `*.egg-info/`, `dist/`, `build/` |
| **OS/editor files** | `.DS_Store`, `Thumbs.db`, `*.swp` | System files |
| **Model weights** | Too large for version control | `models/`, `*.gguf`, `*.bin`, `*.safetensors`, `*.onnx` |
| **Secrets** | API keys, tokens | `.env`, `.env.*` |
| **Agent runtime config** | Taste profile, session memory | `.commandcode/`, `.nabd/`, `.nabd_agent_state.json` |

---

## C. Rules

### Rule 1: Generated evidence stays out of product commits
Any file whose primary purpose is to **document a verification result** (gate pass/fail, evidence tables, regression comparisons) is excluded from the source tree. These are living documents of the verification process, not of the product.

### Rule 2: Forensics stays out of product commits
Auto-generated DNA analysis reports (`dna_report.json`, `forensics_report*.md`, `ARCHITECTURE_DNA.md`) are snapshots of code structure at a point in time. They are not source code and must not be committed alongside source changes.

### Rule 3: Scratch/fix scripts stay out unless promoted by explicit review
One-off scripts (`fix_*.py`, `scratch_*.py`, `update_*.py`) are temporary helpers for a specific operation. If a script becomes a permanent tool, it must be:
1. Reviewed: does it have a permanent home in the codebase?
2. Moved: to `scripts/` or `tools/` with proper documentation
3. Promoted: added to commit plan as a first-class source file

### Rule 4: Recovery bundles stay external or gitignored
Directories like `.recovery_bundle/`, `.phase2_backup/`, `.phase22a_recovery/` are operational safety nets. They are useful on disk but must never be committed.

### Rule 5: Any exception must be explicitly justified
If a file that matches an exclusion pattern needs to be committed, the reason must be documented in the commit message and noted in this policy. Examples of valid exceptions:
- A scratch script that evolved into a permanent tool
- A forensics report that documents a security finding needed in the historical record
- A gate artifact that needs to be archived with a specific release

---

## D. Concrete Current Tree Examples

| Category | Example | Policy Status | Mechanism |
|:---------|:--------|:--------------|:----------|
| Source (new) | `core/turn_outcome.py` | ✅ INCLUDED | Tracked or to be committed |
| Source (modified) | `engine/loop.py` | ✅ INCLUDED | Modified tracked file |
| Test (new) | `tests/test_gate_l1_loop_semantics.py` | ✅ INCLUDED | To be committed in C5 |
| Test (modified) | `tests/test_phase5_harden.py` | ✅ INCLUDED | To be committed in C4 |
| Gate artifact | `l6_behavioral_evidence_matrix.md` | ❌ EXCLUDED | `.gitignore` pattern |
| Gate artifact | `l7_baseline_regression_report.md` | ❌ EXCLUDED | `.gitignore` pattern |
| Gate artifact | `l8_closure_report.md` | ❌ EXCLUDED | `.gitignore` pattern |
| Incident postmortem | `loop_v3_unauthorized_change_incident.md` | ❌ EXCLUDED | Not in `.gitignore` yet; externally stored |
| Forensics | `forensics_report.md` | ❌ EXCLUDED | `.gitignore` pattern (already tracked — history preserved) |
| Fix script | `fix_all_tmp.py` | ❌ EXCLUDED | `.gitignore` pattern |
| Scratch test | `scratch_type_test.py` | ❌ EXCLUDED | `.gitignore` pattern |
| Test output | `report.txt23` | ❌ EXCLUDED | `.gitignore` pattern (`report.txt*`) |
| Runtime state | `STATE.md` | ❌ EXCLUDED | `.gitignore` pattern |

---

## E. Note on Already-Tracked Files

Some excluded-category files are **already tracked in git history** (e.g., `forensics_report*.md`). Adding them to `.gitignore`:
- ✅ Prevents accidental re-staging if deleted and recreated
- ⚠️ Does NOT remove them from git tracking
- To fully remove from tracking: `git rm --cached <file>` (requires explicit review)

This policy governs **future commits**, not past history. Already-tracked files remain in git history unless explicitly removed.
