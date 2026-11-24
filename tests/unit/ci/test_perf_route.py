import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "perf_route.py"
_spec = importlib.util.spec_from_file_location("perf_route", SCRIPT)
perf_route = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(perf_route)


@pytest.mark.parametrize(
    "paths, mode",
    [
        (["README.md", "docs/performance/x.png", "CHANGELOG.md"], "skip"),
        (["CHANGELOG.md", "grow/views.py"], "full"),
        ([".github/workflows/perf.yml"], "full"),
        (["scripts/perf_route.py"], "full"),
        (["scripts/perf_ab.sh"], "full"),
        ([".github/workflows/validate.yml"], "skip"),
        (["grow/x.py", "docs/x.py"], "full"),  # rename grow/x.py -> docs/x.py lists both names
        (["docs/deleted.md"], "skip"),
        ([], "full"),
        (["Unknown.cfg"], "full"),
        ([".github/workflows/new.yml"], "full"),
        (["pyproject.toml"], "full"),
        (["uv.lock"], "full"),
        (["tests/utils/AppApiClient.py"], "full"),
        (["benchmarks/catalogue/catalogue_restore.py"], "full"),
        (["benchmarks/catalogue/tests/test_x.py"], "skip"),
    ],
)
def test_classify(paths, mode):
    assert perf_route.classify(paths)[0] == mode


def test_allowlist_entries_exist():
    for f in perf_route.SKIP_FILES:
        assert (ROOT / f).is_file(), f
    for prefix in perf_route.SKIP_PREFIXES:
        if prefix != ".pr-descriptions/":  # created on demand
            assert (ROOT / prefix).is_dir(), prefix


@pytest.mark.parametrize(
    "stdin, line", [(b"README.md\0docs/a.md\0", "mode=skip"), (b"README.md\0grow/a.py\0", "mode=full")]
)
def test_cli(stdin, line):
    out = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, check=True).stdout
    assert out.decode().strip() == line
