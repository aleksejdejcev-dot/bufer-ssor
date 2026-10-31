import ast
import inspect
from pathlib import Path
from repo.base import Repository
from repo.in_memory_repo import InMemoryRepo
from repo.supabase_repo import SupabaseRepo


def get_interface_methods(protocol_cls):
    return {
        name for name, val in inspect.getmembers(protocol_cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_repo_implementations_match_interface():
    interface_methods = get_interface_methods(Repository)
    assert len(interface_methods) > 15, "Интерфейс Repository должен содержать методы доступа к данным"

    in_memory_methods = {
        name for name, val in inspect.getmembers(InMemoryRepo, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    supabase_methods = {
        name for name, val in inspect.getmembers(SupabaseRepo, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    missing_in_memory = interface_methods - in_memory_methods
    assert not missing_in_memory, f"В InMemoryRepo отсутствуют методы интерфейса: {missing_in_memory}"

    missing_supabase = interface_methods - supabase_methods
    assert not missing_supabase, f"В SupabaseRepo отсутствуют методы интерфейса: {missing_supabase}"


def test_ast_repo_calls_exist_in_interface():
    interface_methods = get_interface_methods(Repository)
    backend_dir = Path(__file__).resolve().parent.parent

    repo_calls = set()

    for py_file in backend_dir.rglob("*.py"):
        if "tests" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr_name = node.func.attr
                # Проверяем вызовы вида repo.<method>(...) или get_repo().<method>(...) или db.<method>(...)
                if isinstance(node.func.value, ast.Name) and node.func.value.id in ("repo", "repository"):
                    repo_calls.add(attr_name)
                elif isinstance(node.func.value, ast.Call) and isinstance(node.func.value.func, ast.Name) and node.func.value.func.id == "get_repo":
                    repo_calls.add(attr_name)

    missing_methods = repo_calls - interface_methods
    assert not missing_methods, f"Найдены вызовы repo методов, отсутствующих в Repository: {missing_methods}"
