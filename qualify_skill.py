import os, tempfile
from pathlib import Path
from unittest.mock import patch
from core.skills import discover_skills, execute_skill, ShellPermissions
from core.evidence import EvidenceLog

with tempfile.TemporaryDirectory() as tmp:
    target = os.path.join(tmp, "note.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("hello from skill\n")
    
    skill_dir = Path(tmp) / "catfile"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("+++\nname: catfile\ndescription: cat a file\nallowed_tools: ['cat *']\ncommand: cat {target}\n+++")
    
    with patch("core.skills.Path.home", return_value=Path(tmp) / "no_home"):
        skills = discover_skills(Path(tmp))
        skill = skills[0]
        
    state = type("S", (), {"shell_permissions": ShellPermissions()})()
    result = execute_skill(skill, state=state, evidence_log=EvidenceLog(), args=target)
    print("SUCCESS:", result.success)
    print("STDERR:", result.stderr)
    print("STDOUT:", result.stdout)
