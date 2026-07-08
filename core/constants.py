from typing import Final, Set

SAFE_BINARIES: Final[Set[str]] = {
    "ls", "pwd", "echo", "whoami", "cat", "grep", "date", 
    "ps", "uptime", "df", "free", "history", "clear", "find", "wc",
    "du", "sort", "head", "tail", "awk", "top",
    "termux-battery-status", "termux-telephony-deviceinfo",
    "git", "xargs", "python", "python3", "pip", "uname", "id", "env",
    "uvicorn", "curl", "wget", "sleep", "kill", "pkill", "lsof", "pytest",
    "node", "npm", "npx", "nohup", "bash", "sh", "setsid", "killall"
}

DANGEROUS_STRICT: Final[Set[str]] = {";", "`", "$("}
