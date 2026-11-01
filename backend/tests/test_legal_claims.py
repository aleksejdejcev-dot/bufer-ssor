import re
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

FORBIDDEN_PATTERNS = [
    r"152-фз",
    r"строгом соответствии",
    r"хранится в рф",
    r"полностью защищ",
    r"гарантирует",
]


def test_no_forbidden_legal_claims_in_codebase():
    """Проверяет отсутствие утверждений о 'соответствии 152-ФЗ', 'гарантиях' и т.д."""
    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]

    paths_to_scan = [
        ROOT_DIR / "README.md",
        ROOT_DIR / "backend",
        ROOT_DIR / "frontend" / "src",
        ROOT_DIR / "db",
        ROOT_DIR / "docs",
    ]

    violations = []

    for path in paths_to_scan:
        if path.is_file():
            files = [path]
        else:
            files = [
                f for f in path.rglob("*")
                if f.is_file() and not any(part.startswith(".") or part in ("__pycache__", "venv", ".venv") for part in f.parts)
                and f.name != "test_legal_claims.py"  # сам тестовый файл содержит паттерны
            ]

        for f in files:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue

            for pattern in compiled_patterns:
                matches = pattern.findall(content)
                if matches:
                    violations.append(f"Файл {f.relative_to(ROOT_DIR)}: обнаружен паттерн '{pattern.pattern}' ({len(matches)} раз)")

    assert not violations, "Обнаружены недопустимые юридические утверждения:\n" + "\n".join(violations)


def test_legal_modal_contains_draft_banner():
    """Проверяет наличие предупреждающего баннера в LegalModal.jsx."""
    modal_file = ROOT_DIR / "frontend" / "src" / "components" / "LegalModal.jsx"
    assert modal_file.exists(), "LegalModal.jsx не найден"
    content = modal_file.read_text(encoding="utf-8")
    assert "Черновик, требует проверки юристом. Не является публичной офертой" in content


def test_readme_contains_factual_statements():
    """Проверяет, что README содержит фактические формулировки об инфраструктуре и отсутствии аудита."""
    readme_file = ROOT_DIR / "README.md"
    assert readme_file.exists()
    content = readme_file.read_text(encoding="utf-8")
    assert "[провайдер, регион: заполняет владелец]" in content
    assert "Юридический аудит проекта не проводился" in content
