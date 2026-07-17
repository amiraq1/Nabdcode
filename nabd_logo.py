import os
import shutil
import subprocess

from rich.console import Console

console = Console()


def get_git_repository_name():
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            return os.path.basename(result.stdout.strip())
    except Exception:
        pass
    return "Local Workspace"


def draw(model_name="ORCA-FLASH"):
    # تقسيم أسطر الشعار لتلوين كل سطر بشكل مستقل
    logo_lines = [
        "█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀",  # السطر العلوي
        "█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄"   # السطر السفلي
    ]

    # تحديد الأكواد القياسية: الأول أبيض عريض، والثاني رصاصي/رمادي مخفف
    colors = [
        "[bold white]",  # Bold White
        "[#555555]",     # Dark Gray / Gray
    ]
    reset = "[/]"

    # جلب اسم المستودع الحالي ديناميكياً
    repo_name = get_git_repository_name()

    # صياغة معلومات النظام بعد حذف الـ Version
    metadata = f"Repo: {repo_name}  •  Model: {model_name}"

    columns, _ = shutil.get_terminal_size()

    # Hard ANSI reset — consistent Termux clear (through Rich)
    console.print("\033c", end="")

    # 1. طباعة الشعار وحساب التوسط يدوياً لتفادي تشويه الألوان
    for line, color in zip(logo_lines, colors):
        padding = max(0, (columns - len(line)) // 2)
        console.print(" " * padding + color + line + reset)

    console.print()

    # 2. طباعة معلومات النظام النظيفة بمنتصف الشاشة
    console.print(metadata.center(columns))
    console.print("-" * columns)


print_nabd_logo = draw

if __name__ == "__main__":
    draw()
