"""Packaging configuration for NABD OS (nabdcode).

Mobile-first AI CLI agent for Termux. Builds a distributable ``nabdcode``
console command via setuptools.
"""

from __future__ import annotations

import os

from setuptools import setup, find_packages


def read_requirements() -> list:
    """Parse requirements.txt, ignoring comments/blank lines.

    Falls back to a hardcoded core list if the file is missing or empty.
    """
    fallback = [
        "prompt_toolkit>=3.0.0",
        "rich>=13.0.0",
    ]
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not os.path.isfile(req_path):
        return fallback
    requirements = []
    with open(req_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            requirements.append(line)
    return requirements or fallback


def read_long_description() -> str:
    """Read README.md for the PyPI long description; safe fallback if absent."""
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    if os.path.isfile(readme_path):
        with open(readme_path, "r", encoding="utf-8") as fh:
            return fh.read()
    return (
        "A powerful mobile-first AI CLI agent designed for Termux."
    )


setup(
    name="nabdcode",
    version="1.0.0",
    author="Ammar Al-Tamimi",
    url="https://github.com/amiraq1",
    description="A powerful mobile-first AI CLI agent designed for Termux.",
    long_description=read_long_description(),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    install_requires=read_requirements(),
    entry_points={
        # Entry point: main.py defines `def main():`. Module path is `main:main`.
        # Adjust the module path if your package layout differs.
        # e.g. core.cli:main  ->  <package>.<module>:<function>
        "console_scripts": [
            "nabdcode=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Android",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Terminals",
        "Topic :: Utilities",
    ],
    py_modules=["main", "llm_router", "nabd_logo", "vfs"],
    packages=find_packages(include=["core*", "engine*", "tools*", "ui*"]),
    include_package_data=True,
)
