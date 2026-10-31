#!/usr/bin/env python3
"""
Резервный сканер секретов (когда gitleaks не установлен в окружении).
"""
import re
import sys
from pathlib import Path

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__"}
IGNORED_FILES = {".env", ".env.example", "russian_trusted_root_ca.pem"}

PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z-_]{35}"), "Google API Key"),
    (re.compile(r"\b[0-9]{8,10}:AA[0-9A-Za-z_-]{33}\b"), "Telegram Bot Token"),
    (re.compile(r"MDFhMTkxMGMt[0-9a-zA-Z-]{36}:[0-9a-zA-Z-]{36}=="), "GigaChat Key"),
]

def scan_file(path: Path) -> list:
    findings = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    for lineno, line in enumerate(content.splitlines(), start=1):
        for pat, desc in PATTERNS:
            if pat.search(line):
                findings.append((path, lineno, desc))
    return findings

def main():
    root = Path(__file__).resolve().parent.parent
    findings = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in IGNORED_DIRS for part in p.parts):
            continue
        if p.name in IGNORED_FILES:
            continue
        findings.extend(scan_file(p))

    if findings:
        print(f"❌ Обнаружено секретов: {len(findings)}")
        for path, line, desc in findings:
            print(f"  - {path}:{line} ({desc})")
        sys.exit(1)
    else:
        print("✅ Утечек секретов не обнаружено (no-gitleaks scan passed)")
        sys.exit(0)

if __name__ == "__main__":
    main()
