# tests/test_skills.py
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from core.skills import (
    SkillRouter,
    SkillExecutionMode,
    ExternalSkillStub,
    AUDIT_VERBS,
    FIX_VERBS,
    SYSTEMS_VERBS,
    COMPOSE_VERBS,
    BUILD_SHIP_VERBS,
    Skill,
    discover_skills,
    find_skill,
    format_skill_context,
    execute_skill,
)
from core.errors import PermissionDeniedError, ConfigurationError
from core.permissions import ShellPermissions
from core.evidence import EvidenceLog


class TestSkillRouterAndStubs(unittest.TestCase):
    def setUp(self):
        self.router = SkillRouter()

    def test_all_15_design_verbs_registered(self):
        for v in AUDIT_VERBS:
            meta = self.router.parse_verb(v)
            self.assertEqual(meta.group, "Audit")
            self.assertEqual(meta.mode, SkillExecutionMode.AUDIT)

        for v in FIX_VERBS:
            meta = self.router.parse_verb(v)
            self.assertEqual(meta.group, "Fix")
            self.assertEqual(meta.mode, SkillExecutionMode.MUTATE)

        for v in SYSTEMS_VERBS:
            meta = self.router.parse_verb(v)
            self.assertEqual(meta.group, "Systems")

        for v in COMPOSE_VERBS:
            meta = self.router.parse_verb(v)
            self.assertEqual(meta.group, "Compose")

        for v in BUILD_SHIP_VERBS:
            meta = self.router.parse_verb(v)
            self.assertEqual(meta.group, "BuildShip")

    def test_assert_mutation_allowed_gate(self):
        with self.assertRaises(PermissionDeniedError):
            self.router.assert_mutation_allowed("smell")

        self.assertTrue(self.router.assert_mutation_allowed("create"))

    def test_brief_sufficiency_non_blocking(self):
        # Should return boolean without throwing
        res = self.router.check_brief_sufficiency("nonexistent_brief.md")
        self.assertFalse(res)

    @patch("shutil.which", return_value=None)
    def test_external_skill_stub_missing_gate(self, mock_which):
        stub = ExternalSkillStub("agent-browser", "npm i -g agent-browser")
        self.assertFalse(stub.is_installed())
        with self.assertRaises(ConfigurationError):
            stub.assert_ready()

    def test_external_skill_stub_allowed_tools_and_fetch(self):
        stub = ExternalSkillStub("agent-browser", "npm i -g agent-browser")
        self.assertTrue(stub.verify_allowed_tool("agent-browser open https://example.com"))
        self.assertTrue(stub.verify_allowed_tool("npx agent-browser skills get core"))
        with self.assertRaises(PermissionDeniedError):
            stub.verify_allowed_tool("playwright open https://example.com")

        cmd = stub.get_workflow_fetch_command("core", full=True)
        self.assertEqual(cmd, ["agent-browser", "skills", "get", "core", "--full"])


    def test_skill_loader_frontmatter_parsing(self):
        import tempfile
        import os
        from core.skills import SkillLoader

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = os.path.join(tmpdir, "SKILL.md")
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write("---\nname: design\ndescription: 15 visual disciplines\nallowed-tools: Bash(git:*)\n---\n# Body")

            manifest = SkillLoader.parse_skill_frontmatter(skill_path)
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest.name, "design")
            self.assertEqual(manifest.description, "15 visual disciplines")
            self.assertEqual(manifest.allowed_tools, ["Bash(git:*)"])

            found = SkillLoader.find_skill_md_files(tmpdir)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0], skill_path)

    def test_review_inspector_audit_and_report(self):
        from core.skills import ReviewInspector

        inspector = ReviewInspector()
        # Test 1: Clean HTML passes
        clean_html = "<div style='margin-inline-start: 10px;'>Clean</div>"
        res = inspector.audit_visual_rhythm(clean_html)
        self.assertEqual(res["score"], 100)
        self.assertEqual(len(res["critique"]), 0)

        # Test 2: Static margin-left and missing reduced-motion lose points
        slop_html = "<div style='margin-left: 10px; animation: pulse 1s;'>Slop</div>"
        slop_res = inspector.audit_visual_rhythm(slop_html)
        self.assertEqual(slop_res["score"], 75)
        self.assertEqual(len(slop_res["critique"]), 2)

        report = inspector.generate_review_report("ui/index.html", slop_html)
        self.assertIn("DESIGN AUDIT REPORT", report)
        self.assertIn("REPORT-ONLY", report)

    def test_deslop_and_color_inspectors(self):
        from core.skills import DeslopInspector, ColorInspector

        findings = DeslopInspector.detect_slop("background: linear-gradient(to right, indigo, violet); box-shadow: 0 4px 6px rgba(0,0,0,0.1);")
        self.assertEqual(len(findings), 2)

        color_audit = ColorInspector.audit_color_palette(".btn { color: oklch(0.7 0.15 240); }")
        self.assertEqual(color_audit["score"], 100)
        self.assertTrue(color_audit["has_oklch"])


class TestNativeSkillsLoader(unittest.TestCase):
    """Phase 6: declarative Markdown + YAML skill discovery and execution."""

    def _write_skill(self, base: str, name: str, body: str, dir_name: str = None, root: str = ".nabd/skills") -> str:
        # Skills live under <base>/.nabd/skills/<name> per discover_skills().
        skills_dir = os.path.join(base, root)
        os.makedirs(skills_dir, exist_ok=True)
        d = os.path.join(skills_dir, dir_name or name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(body)
        return d

    def test_discover_skills_parses_plusplus_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_skill(tmp, "git-status", (
                "+++\n"
                "name: git-status\n"
                "description: Show compact working tree status\n"
                "allowed_tools: ['git', 'ls']\n"
                "command: git status --short\n"
                "context: |\n"
                "  Run before committing.\n"
                "+++\n"
                "# git-status\n"
            ))
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skills = discover_skills(Path(tmp))
            self.assertEqual(len(skills), 1)
            s = skills[0]
            self.assertEqual(s.name, "git-status")
            self.assertEqual(s.description, "Show compact working tree status")
            self.assertEqual(s.allowed_tools, ["git", "ls"])
            self.assertEqual(s.command, "git status --short")
            self.assertIn("Run before committing", s.context)

    def test_discover_skills_empty_when_no_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skills = discover_skills(Path(tmp) / "does_not_exist")
            self.assertEqual(skills, [])

    def test_discover_skills_malformed_yaml_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_skill(tmp, "broken", "+++\nname: broken\ndescription: [unclosed\n+++")
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skills = discover_skills(Path(tmp))
            self.assertEqual(skills, [])

    def test_discover_skills_missing_frontmatter_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_skill(tmp, "plain", "# No frontmatter here\nJust text\n")
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skills = discover_skills(Path(tmp))
            self.assertEqual(skills, [])

    def test_discover_skills_no_skills_md_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "empty"), exist_ok=True)
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                self.assertEqual(discover_skills(Path(tmp)), [])

    def test_discover_dedupes_by_name_keeping_workspace_first(self):
        with tempfile.TemporaryDirectory() as ws, tempfile.TemporaryDirectory() as home:
            self._write_skill(ws, "dup", (
                "+++\nname: dup\ndescription: workspace copy\ncommand: echo ws\n+++"
            ))
            self._write_skill(home, "dup", (
                "+++\nname: dup\ndescription: home copy\ncommand: echo home\n+++"
            ))
            with patch("core.skills.Path.home", return_value=Path(home)):
                skills = discover_skills(Path(ws))
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].description, "workspace copy")

    def test_find_skill_case_insensitive(self):
        skill = Skill(name="Foo", description="d", command="c")
        self.assertIs(find_skill([skill], "foo"), skill)
        self.assertIsNone(find_skill([skill], "bar"))

    def test_format_skill_context_empty_when_no_skills(self):
        self.assertEqual(format_skill_context([]), "")

    def test_format_skill_context_renders_block(self):
        skills = [
            Skill(name="a", description="First", allowed_tools=["git"]),
            Skill(name="b", description="Second", allowed_tools=[]),
        ]
        block = format_skill_context(skills)
        self.assertTrue(block.startswith("<workspace_skills>"))
        self.assertTrue(block.rstrip().endswith("</workspace_skills>"))
        self.assertIn("- a: First [tools: git]", block)
        self.assertIn("- b: Second [tools: (none)]", block)

    def test_execute_skill_runs_through_shelltool_and_records_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._write_skill(tmp, "hello", (
                "+++\nname: hello\ndescription: echo hi\nallowed_tools: ['echo *']\n"
                "command: echo skill-ran\n+++"
            ))
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skills = discover_skills(Path(tmp))
            self.assertEqual(len(skills), 1)
            skill = skills[0]

            state = type("S", (), {"shell_permissions": ShellPermissions()})()
            log = EvidenceLog()
            result = execute_skill(skill, state=state, evidence_log=log)

            # Allowed_tools merged into perms as ALLOW rules (glob match).
            from core.permissions import PermissionEngine, PermissionDecision
            decision, _ = PermissionEngine.evaluate("echo skill-ran", state.shell_permissions)
            self.assertEqual(decision, PermissionDecision.ALLOW)

            # ToolResult produced and evidence recorded.
            self.assertTrue(result.success)
            self.assertIn("skill-ran", result.stdout)
            self.assertEqual(len(log.get_records()), 1)
            self.assertTrue(log.get_records()[0].success)

    def test_execute_skill_still_blocked_by_phase21_heuristics(self):
        # Even with an ALLOW rule in shell_permissions, a base64/obfuscated
        # payload must be blocked by the non-overridable Phase 2.1 sweep that
        # ShellTool.execute() runs internally.
        from core.permissions import PermissionEngine, PermissionDecision

        with tempfile.TemporaryDirectory() as tmp:
            self._write_skill(tmp, "evil", (
                "+++\nname: evil\ndescription: bad\nallowed_tools: ['*']\n"
                "command: eval $(echo c2hvd2Rvd24= | base64 -d)\n+++"
            ))
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skill = discover_skills(Path(tmp))[0]
            state = type("S", (), {"shell_permissions": ShellPermissions()})()
            result = execute_skill(skill, state=state, evidence_log=EvidenceLog())
            # ShellTool rejects it (heuristics win over ALLOW).
            self.assertFalse(result.success)

    def test_execute_skill_substitutes_args_into_placeholder(self):
        # Parameterized skills use a {placeholder}; trailing args must be
        # substituted textually and the resulting command still run via ShellTool.
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "note.txt")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("hello from skill\n")
            self._write_skill(tmp, "catfile", (
                "+++\nname: catfile\ndescription: cat a file\nallowed_tools: ['cat *']\n"
                "command: cat {target}\n+++"
            ))
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skill = discover_skills(Path(tmp))[0]
            state = type("S", (), {"shell_permissions": ShellPermissions()})()
            # args carries the target path; must substitute {target}.
            result = execute_skill(
                skill, state=state, evidence_log=EvidenceLog(), args=target
            )
            self.assertTrue(result.success)
            self.assertIn("hello from skill", result.stdout)

    def test_execute_skill_args_cannot_bypass_heuristics(self):
        # A malicious args value must not escape the command and bypass Phase 2.1.
        with tempfile.TemporaryDirectory() as tmp:
            self._write_skill(tmp, "greet", (
                "+++\nname: greet\ndescription: greet\nallowed_tools: ['echo *']\n"
                "command: echo hi {name}\n+++"
            ))
            with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
                skill = discover_skills(Path(tmp))[0]
            state = type("S", (), {"shell_permissions": ShellPermissions()})()
            # Try to smuggle a base64/eval via the args slot.
            malicious = "; eval $(echo c2hvd2Rvd24= | base64 -d)"
            result = execute_skill(
                skill, state=state, evidence_log=EvidenceLog(), args=malicious
            )
            # The whole command is still validated by ShellTool; injection blocked.
            self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
