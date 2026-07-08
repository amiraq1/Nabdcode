import os
import subprocess
import zipfile
import shutil

REPORT_DIR = "forensics_report"
if not os.path.exists(REPORT_DIR):
    os.makedirs(REPORT_DIR)

FILES_DIR = os.path.join(REPORT_DIR, "files")
if not os.path.exists(FILES_DIR):
    os.makedirs(FILES_DIR)

LOGS_DIR = os.path.join(REPORT_DIR, "logs")
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Run system commands
def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        return str(e.output)
    except Exception as e:
        return str(e)

with open(os.path.join(REPORT_DIR, "system_info.txt"), "w") as f:
    f.write("=== Project Info ===\n")
    f.write(run_cmd("ls -R | grep ':$' | sed -e 's/:$//' -e 's/[^-][^\/]*\//--/g' -e 's/^/   /' -e 's/-/|/'")) # simple tree alt
    f.write("\n\n-- PWD --\n")
    f.write(run_cmd("pwd"))
    f.write("\n\n-- PYTHON --\n")
    f.write(run_cmd("python3 --version"))
    f.write("\n\n-- PIP --\n")
    f.write(run_cmd("pip list"))
    f.write("\n\n-- LS --\n")
    f.write(run_cmd("ls -la"))
    f.write("\n\n-- GIT --\n")
    f.write(run_cmd("git status"))
    f.write(run_cmd("git branch"))
    f.write(run_cmd("git rev-parse --short HEAD"))

# Copy files
targets = [
    "main.py", "agent_executor.py", "cli.py", "prompt_cli.py", "app.py", "run.py", "launcher.py",
    "console.py", "ui.py", "layout.py", "renderer.py", "screen.py", "display.py", "status.py", "header.py", "footer.py", "prompt.py",
    "requirements.txt", "pyproject.toml", "setup.py", "package.json", ".env.example"
]
for root, dirs, files in os.walk("."):
    if "forensics_report" in root or "__pycache__" in root or "sessions" in root:
        continue
    for file in files:
        if file in targets or file.startswith("config."):
            shutil.copy2(os.path.join(root, file), FILES_DIR)

# Greps
grep_targets = [
    "from rich", "Console(", "Live(", "Panel(", "Layout(", "PromptSession", "Application(", "prompt_toolkit",
    "clear", "os.system", "cls", "console.clear", "refresh", "render", "invalidate",
    "print(",
    "thread", "asyncio", "run_in_executor", "ThreadPool", "ProcessPool"
]

with open(os.path.join(REPORT_DIR, "grep_results.txt"), "w") as f:
    for q in grep_targets:
        f.write(f"\n\n=== GREP: {q} ===\n")
        f.write(run_cmd(f"grep -RIn '{q}' . --exclude-dir=forensics_report --exclude-dir=sessions --exclude-dir=__pycache__"))

# Logs
if os.path.exists("ui_violation.log"):
    shutil.copy2("ui_violation.log", LOGS_DIR)
if os.path.exists("sessions"):
    for root, dirs, files in os.walk("sessions"):
        for file in files:
            shutil.copy2(os.path.join(root, file), LOGS_DIR)

# Zip
with zipfile.ZipFile("forensics_report.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(REPORT_DIR):
        for file in files:
            zipf.write(os.path.join(root, file))

print("Forensics collection complete.")
