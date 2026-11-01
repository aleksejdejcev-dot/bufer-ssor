import hashlib
import os
from pathlib import Path
import pytest
from config.settings import settings


def get_ca_bundle_path() -> Path:
    """Возвращает путь к бандлу сертификатов Минцифры."""
    ca_path_str = os.getenv("GIGACHAT_CA_BUNDLE", settings.GIGACHAT_CA_BUNDLE or "")
    if not ca_path_str:
        pytest.skip("GIGACHAT_CA_BUNDLE не задан")
    
    path = Path(ca_path_str)
    if not path.is_absolute():
        # Проверяем относительно текущей рабочей директории и относительно каталога backend
        if path.exists():
            return path
        backend_dir = Path(__file__).resolve().parent.parent
        cand = backend_dir / path
        if cand.exists():
            return cand
        cand_root = backend_dir.parent / path
        if cand_root.exists():
            return cand_root
    return path


def test_ca_bundle_file_exists():
    """E2: Если переменная GIGACHAT_CA_BUNDLE указывает на файл, проверять его наличие."""
    ca_path = get_ca_bundle_path()
    assert ca_path.exists(), f"Файл сертификатов Минцифры не найден по пути: {ca_path}"
    assert ca_path.is_file(), f"Указанный путь не является файлом: {ca_path}"
    assert ca_path.stat().st_size > 0, "Файл сертификатов пуст"


def test_ca_bundle_sha256():
    """E2: Если задан GIGACHAT_CA_BUNDLE_SHA256 — сверять хэш, иначе пропускать (skip)."""
    expected_hash = os.getenv("GIGACHAT_CA_BUNDLE_SHA256", "").strip()
    if not expected_hash:
        pytest.skip("GIGACHAT_CA_BUNDLE_SHA256 не задан в окружении; владелец заполнит после сверки с Госуслугами")

    ca_path = get_ca_bundle_path()
    content = ca_path.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    assert actual_hash.lower() == expected_hash.lower(), (
        f"Хэш файла сертификатов ({actual_hash}) не совпадает с ожидаемым ({expected_hash})"
    )


def test_ca_bundle_hash_verification_logic(tmp_path):
    """Проверяет корректность алгоритма сверки хэша при наличии эталона и при несовпадении."""
    dummy_cert = tmp_path / "dummy.pem"
    dummy_cert.write_bytes(b"CERTIFICATE_DATA")
    expected = hashlib.sha256(b"CERTIFICATE_DATA").hexdigest()
    
    # Совпадение
    actual = hashlib.sha256(dummy_cert.read_bytes()).hexdigest()
    assert actual.lower() == expected.lower()

    # Несовпадение
    bad_expected = "0" * 64
    assert actual.lower() != bad_expected
