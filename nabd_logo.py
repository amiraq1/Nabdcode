import shutil
import sys
import os
import subprocess

def get_git_repository_name():
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            return os.path.basename(result.stdout.strip())
    except Exception:
        pass
    return "Local Workspace"

def draw(model_name="Llama-3.1-70B"):
    # تقسيم أسطر الشعار لتلوين كل سطر بشكل مستقل
    logo_lines = [
        "█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀",  # السطر العلوي
        "█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄"   # السطر السفلي
    ]
    
    # تحديد الأكواد القياسية: الأول أبيض عريض، والثاني رصاصي/رمادي مخفف
    colors = [
        "\033[1;37m",  # Bold White
        "\033[90m"     # Dark Gray / Gray
    ]
    reset = "\033[0m"
    
    # جلب اسم المستودع الحالي ديناميكياً
    repo_name = get_git_repository_name()
    
    # صياغة معلومات النظام بعد حذف الـ Version
    metadata = f"Repo: {repo_name}  •  Model: {model_name}"

    columns, _ = shutil.get_terminal_size()
    
    # تنظيف الشاشة الفوري بكفاءة عتادية مطلقة
    sys.stdout.write("\033[2J\033[H\n\n")
    
    # 1. طباعة الشعار وحساب التوسط يدوياً لتفادي تشويه الألوان
    for line, color in zip(logo_lines, colors):
        padding = max(0, (columns - len(line)) // 2)
        sys.stdout.write(" " * padding + color + line + reset + "\n")
        
    sys.stdout.write("\n")
    
    # 2. طباعة معلومات النظام النظيفة بمنتصف الشاشة
    sys.stdout.write(metadata.center(columns) + "\n")
    sys.stdout.write("\n" + "-" * columns + "\n")
    sys.stdout.flush()

print_nabd_logo = draw

if __name__ == "__main__":
    draw()

