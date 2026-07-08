#!/bin/bash
set -e

cd ~/smart-agent
REPORT_DIR="forensics_report"
mkdir -p "$REPORT_DIR"
mkdir -p "$REPORT_DIR/files"

# 1. معلومات المشروع
echo "=== Project Info ===" > "$REPORT_DIR/system_info.txt"
tree -L 3 >> "$REPORT_DIR/system_info.txt" || echo "tree command failed" >> "$REPORT_DIR/system_info.txt"
pwd >> "$REPORT_DIR/system_info.txt"
python3 --version >> "$REPORT_DIR/system_info.txt"
pip list >> "$REPORT_DIR/system_info.txt"
ls -la >> "$REPORT_DIR/system_info.txt"
git status >> "$REPORT_DIR/system_info.txt" || echo "not a git repo" >> "$REPORT_DIR/system_info.txt"
git branch >> "$REPORT_DIR/system_info.txt" || true
git rev-parse --short HEAD >> "$REPORT_DIR/system_info.txt" || true

# 2-6. نسخ الملفات
find . -type f \( -name "main.py" -o -name "agent_executor.py" -o -name "cli.py" -o -name "prompt_cli.py" -o -name "app.py" -o -name "run.py" -o -name "launcher.py" \) -exec cp {} "$REPORT_DIR/files/" \;
find . -type f \( -name "console.py" -o -name "ui.py" -o -name "layout.py" -o -name "renderer.py" -o -name "screen.py" -o -name "display.py" -o -name "status.py" -o -name "header.py" -o -name "footer.py" -o -name "prompt.py" \) -exec cp {} "$REPORT_DIR/files/" \;
find . -type f \( -name "requirements.txt" -o -name "pyproject.toml" -o -name "setup.py" -o -name "package.json" -o -name "config.*" -o -name ".env.example" \) -exec cp {} "$REPORT_DIR/files/" \;

# 7-11. بحث (Grep)
echo "=== Rich Usages ===" > "$REPORT_DIR/grep_results.txt"
grep -RIn "from rich" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "Console(" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "Live(" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "Panel(" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "Layout(" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "PromptSession" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "Application(" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "prompt_toolkit" . >> "$REPORT_DIR/grep_results.txt" || true

echo -e "\n=== Screen Clears ===" >> "$REPORT_DIR/grep_results.txt"
grep -RIn "clear" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "os.system" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "cls" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "console.clear" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "refresh" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "render" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "invalidate" . >> "$REPORT_DIR/grep_results.txt" || true

echo -e "\n=== Print Usages ===" >> "$REPORT_DIR/grep_results.txt"
grep -RIn "print(" . >> "$REPORT_DIR/grep_results.txt" || true

echo -e "\n=== Threads ===" >> "$REPORT_DIR/grep_results.txt"
grep -RIn "thread" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "asyncio" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "run_in_executor" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "ThreadPool" . >> "$REPORT_DIR/grep_results.txt" || true
grep -RIn "ProcessPool" . >> "$REPORT_DIR/grep_results.txt" || true

# 12. سجل التشغيل (Logs)
mkdir -p "$REPORT_DIR/logs"
cp ui_violation.log "$REPORT_DIR/logs/" 2>/dev/null || true
cp -r sessions/ "$REPORT_DIR/logs/" 2>/dev/null || true

# 14. ضغط النتائج
zip -r forensics_report.zip "$REPORT_DIR"
