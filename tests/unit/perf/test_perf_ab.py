import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "perf_ab.sh"


@pytest.mark.parametrize("with_base", [False, True])
@pytest.mark.parametrize("vacuum_fails", [False, True])
def test_every_measured_round_requires_a_successful_vacuum(tmp_path, with_base, vacuum_fails):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = tmp_path / "events"
    uv = bin_dir / "uv"
    uv.write_text("""#!/usr/bin/env python3
import os
import sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['EVENTS']).open('a') as events:
    if 'pytest' in args:
        events.write(('seed' if '-k' in args else 'measure') + '\\n')
        if '-k' not in args:
            Path(os.environ['PERF_RESULTS']).write_text('{}')
    else:
        events.write('judge\\n')
        # Force the confirmation rounds on A/B runs, then let the final verdict pass.
        if '--base' in args and len(list(Path(os.environ['OUT']).glob('head-*.json'))) < 4:
            sys.exit(1)
""")
    psql = bin_dir / "psql"
    psql.write_text("""#!/usr/bin/env python3
import os
import sys
from pathlib import Path
assert sys.argv[-2:] == ['-c', 'VACUUM (FREEZE, ANALYZE)']
assert 'ON_ERROR_STOP=1' in sys.argv
with Path(os.environ['EVENTS']).open('a') as events:
    events.write('vacuum\\n')
sys.exit(int(os.environ['VACUUM_FAILS']))
""")
    uv.chmod(0o755)
    psql.chmod(0o755)
    base = tmp_path / "base"
    (base / "perf").mkdir(parents=True)
    (base / "perf" / "conftest.py").write_text("PERF_RESULTS")
    out = tmp_path / "out"
    result = subprocess.run(
        ["bash", str(SCRIPT), str(base) if with_base else "none", str(tmp_path), str(out)],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "PERF_PG_URL": "postgres://unused",
            "PERF_ACCEPT_REGRESSIONS": "0",
            "PERF_SUMMARY": "",
            "EVENTS": str(events),
            "OUT": str(out),
            "VACUUM_FAILS": str(int(vacuum_fails)),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    recorded = events.read_text().splitlines()
    assert result.returncode == int(vacuum_fails), result.stderr
    if vacuum_fails:
        assert recorded == ["seed"] * (2 if with_base else 1) + ["vacuum"]
    else:
        assert recorded.count("measure") == (8 if with_base else 2)
        for index, event in enumerate(recorded):
            if event == "measure":
                assert recorded[index - 1] == "vacuum"
        assert recorded.count("vacuum") == recorded.count("measure")
