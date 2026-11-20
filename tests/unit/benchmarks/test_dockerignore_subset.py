import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOGUE = ROOT / "benchmarks" / "catalogue"
PACKAGE = "benchmarks.catalogue."


def shipped_files() -> set[str]:
    prefix = "!benchmarks/catalogue/"
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return {line.removeprefix(prefix) for line in lines if line.startswith(prefix)}


def sibling_imports(name: str) -> list[str]:
    """Modules of benchmarks/catalogue imported by `name`, relatively or absolutely."""
    siblings = []
    for node in ast.walk(ast.parse((CATALOGUE / name).read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            assert node.module, f"{name}: `from . import` is not resolved by this guard"
            siblings.append(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level > 1:
            raise AssertionError(f"{name}: imports outside benchmarks/catalogue are not shipped")
        elif isinstance(node, ast.ImportFrom) and node.module == "benchmarks.catalogue":
            siblings += [alias.name for alias in node.names]
        else:
            absolute = [node.module] if isinstance(node, ast.ImportFrom) else []
            absolute += [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            for module in absolute:
                assert module == "benchmarks.catalogue" or not module.startswith("benchmarks"), (name, module)
                if module and module.startswith(PACKAGE):
                    siblings.append(module.removeprefix(PACKAGE))
    for sibling in siblings:
        assert "." not in sibling, f"{name}: subpackage {sibling} is not resolved by this guard"
    return siblings


def import_closure(entry: str) -> set[str]:
    seen: set[str] = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending += [f"{module}.py" for module in sibling_imports(name)]
    return seen


def test_the_image_ships_exactly_what_export_perf_catalogue_imports():
    # The command imports export_plan and catalogue_restore; catalogue_restore reads the schema tsv at runtime.
    expected = import_closure("export_plan.py") | import_closure("catalogue_restore.py")
    expected |= {"__init__.py", "catalogue-schema.tsv"}
    assert shipped_files() == expected
