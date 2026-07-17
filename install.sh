#!/data/data/com.termux/files/usr/bin/env bash
# Nabd OS — Termux & Edge Device One-Click Installer
# Installs system dependencies, C++ build tools, Python packages, and registers `nabdcode` CLI.

set -e

echo -e "\033[1;36m◈ Nabd OS Installer — Initializing Setup for Termux & Edge Devices...\033[0m"

# Check if running inside Termux
if [ -d "/data/data/com.termux/files/usr" ]; then
    echo -e "\033[1;33m[1/3] Detected Termux environment. Updating packages and installing build dependencies...\033[0m"
    pkg update -y
    pkg install -y python clang cmake make git libffi openssl
else
    echo -e "\033[1;33m[1/3] Standard Linux environment detected. Checking Python environment...\033[0m"
fi

echo -e "\033[1;33m[2/3] Upgrading pip, setuptools, and wheel...\033[0m"
python3 -m pip install --upgrade pip setuptools wheel

echo -e "\033[1;33m[3/3] Installing Nabd OS in editable mode...\033[0m"
if [ -d "/data/data/com.termux/files/usr" ]; then
    # Termux Android requires --no-build-isolation --no-deps so pip uses pre-installed packages without triggering Rust builds
    python3 -m pip install --no-build-isolation --no-deps -e .
else
    python3 -m pip install -e .
fi

echo -e "\033[1;32m✓ Installation complete! Nabd OS is ready.\033[0m"
echo -e "\033[1;36mYou can now open any directory and run:\033[0m"
echo -e "  \033[1;32mnabdcode\033[0m                  (interactive Cyberpunk TUI session)"
echo -e "  \033[1;32mnabdcode \"your task...\"\033[0m   (one-shot task execution)"
