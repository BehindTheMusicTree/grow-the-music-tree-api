import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOGUE = ROOT / "benchmarks" / "catalogue"


def shipped_files() -> set[str]:
    prefix = "!benchmarks/catalogue/"
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return {line.removeprefix(prefix) for line in lines if line.startswith(prefix)}


def import_closure(entry: str) -> set[str]:
    seen: set[str] = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((CATALOGUE / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                assert node.module, f"{name}: bare relative imports are not resolved by this guard"
                pending.append(f"{node.module}.py")
    return seen


def test_the_image_ships_exactly_what_export_perf_catalogue_imports():
    # The command imports export_plan and catalogue_restore; catalogue_restore reads the schema tsv at runtime.
    expected = import_closure("export_plan.py") | import_closure("catalogue_restore.py")
    expected |= {"__init__.py", "catalogue-schema.tsv"}
    assert shipped_files() == expected
