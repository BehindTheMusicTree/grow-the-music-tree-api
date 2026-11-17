"""Throwaway feasibility spike driver (never merged to main). Run from the repository root as root on ubuntu-24.04:
`python -m benchmarks.catalogue.spike.spike <songs> <workdir>`.

Generates the synthetic catalogue, dumps it, restores it through the real
restore_execution under the hosted runtime's container limits, and records
phase timings and resource peaks. Prints a JSON report.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from ..restore_bundle import restore_approved

IMAGE = os.environ.get("POSTGRES_IMAGE", "postgres:16")
UID = 999


def sh(*argv, **kw):
    result = subprocess.run(argv, text=True, capture_output=True, check=False, **kw)
    if result.returncode:
        raise RuntimeError(f"{argv[:3]} exit {result.returncode}: {result.stderr[-2000:]}")
    return result.stdout


def meminfo():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, rest = line.split(":")
        values[key] = int(rest.split()[0]) * 1024
    return values


class Sampler(threading.Thread):
    def __init__(self, container_names, work):
        super().__init__(daemon=True)
        self.containers, self.work, self.stop, self.rows = container_names, work, threading.Event(), []

    def run(self):
        while not self.stop.is_set():
            m = meminfo()
            row = {
                "t": time.time(),
                "mem_used": m["MemTotal"] - m["MemAvailable"],
                "swap_used": m["SwapTotal"] - m["SwapFree"],
                "root_used": shutil.disk_usage("/").used,
                "work_used": shutil.disk_usage(self.work).used,
                "container_rss": 0,
            }
            for name in self.containers:
                try:
                    usage = Path(
                        f"/sys/fs/cgroup/system.slice/docker-{sh('docker', 'inspect', '-f', '{{.Id}}', name).strip()}.scope/memory.current"
                    )
                    row["container_rss"] = max(row["container_rss"], int(usage.read_text()))
                except Exception:
                    pass
            self.rows.append(row)
            self.stop.wait(5)

    def summary(self):
        peak = lambda key: max((r[key] for r in self.rows), default=0)  # noqa: E731
        total = shutil.disk_usage("/").total
        return {
            "peak_mem_used_gib": round(peak("mem_used") / 2**30, 2),
            "peak_swap_used_gib": round(peak("swap_used") / 2**30, 2),
            "peak_container_memory_gib": round(peak("container_rss") / 2**30, 2),
            "peak_root_used_pct": round(100 * peak("root_used") / total, 1),
            "peak_work_used_gib": round(peak("work_used") / 2**30, 2),
        }


class Timer(dict):
    def __call__(self, name):
        timings = self

        class Scope:
            def __enter__(self):
                self.start = time.time()

            def __exit__(self, *exc):
                timings[name] = round(time.time() - self.start, 1)

        return Scope()


class Transport:
    """Postgres protocol adapter over docker exec, recording per-call durations."""

    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def run(self, program, arguments, stdin=None):
        start = time.time()
        result = subprocess.run(
            ["docker", "exec", "-i", "-u", "postgres", self.name, program, *arguments],
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
        )
        label = program if stdin is None else f"{program}:{stdin[:24]!r}"
        self.calls.append([label, round(time.time() - start, 1)])
        if result.returncode:
            raise RuntimeError(f"{program} failed: {result.stderr[-2000:]}")
        return result.stdout


def start(name, data, extra, command):
    sh("docker", "rm", "-f", name) if subprocess.run(
        ["docker", "inspect", name], capture_output=True, check=False
    ).returncode == 0 else None
    sh("docker", "run", "-d", "--name", name, *extra, IMAGE, *command)
    for _ in range(120):
        if subprocess.run(["docker", "exec", "-u", "postgres", name, "pg_isready", "-q"], check=False).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError(f"{name} did not become ready")


def main():
    songs, work = int(sys.argv[1]), Path(sys.argv[2])
    search = os.environ.get("REBUILD_SEARCH") == "true"
    # The hosted runtime assumes 4 CPUs; the free runner may offer fewer, which is itself a spike finding.
    cpus = min(4, os.cpu_count() or 1)
    report, timer, calls = {"songs": songs, "runner_cpus": cpus, "runner_df": {}}, Timer(), []
    bundle, gen_data, restore_data = work / "bundle", work / "gen-data", work / "restore-data"
    for path in (bundle, gen_data, restore_data):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    Path(work).chmod(0o755)
    synthetic_bundle_dir = work / "sql"
    sampler = Sampler(["gen", "restore"], str(work))
    sampler.start()
    try:
        with timer("generate_sql_files"):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "benchmarks.catalogue.spike.synthetic_bundle",
                    str(synthetic_bundle_dir),
                    str(songs),
                ],
                check=True,
            )
        pre, post = [(synthetic_bundle_dir / n).read_bytes() for n in ("pre-data.sql", "post-data.sql")]
        os.chown(gen_data, UID, UID)
        Path(bundle).chmod(0o777)
        gen = [
            "-v",
            f"{gen_data}:/var/lib/postgresql/data",
            "-v",
            f"{bundle}:/out",
            "-v",
            f"{synthetic_bundle_dir}:/sql:ro",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
        ]
        tuning = [
            "-c",
            "fsync=off",
            "-c",
            "full_page_writes=off",
            "-c",
            "synchronous_commit=off",
            "-c",
            "max_wal_size=16GB",
            "-c",
            "checkpoint_timeout=30min",
            "-c",
            "shared_buffers=2GB",
            "-c",
            "wal_level=minimal",
            "-c",
            "max_wal_senders=0",
        ]
        with timer("generator_start"):
            start("gen", gen_data, gen, ["postgres", *tuning])
        gt = Transport("gen", [])
        with timer("generate_data"):
            gt.run("psql", ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", "postgres", "-c", "CREATE DATABASE src"])
            gt.run("psql", ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", "src", "-f", "/sql/pre-data.sql"])
            gt.run("psql", ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", "src", "-f", "/sql/generate.sql"])
        report["generated_db_gib"] = round(
            int(gt.run("psql", ["-X", "-Atq", "-d", "src", "-c", "SELECT pg_database_size('src')"])) / 2**30, 2
        )
        with timer("dump"):
            gt.run("pg_dump", ["-Fc", "-Z", "1", "-d", "src", "-f", "/out/backup.dump"])
        sh("docker", "rm", "-f", "gen")
        shutil.rmtree(gen_data)
        dump = bundle / "backup.dump"
        digest = hashlib.sha256()
        with timer("dump_sha256"), dump.open("rb") as source:
            for block in iter(lambda: source.read(1 << 20), b""):
                digest.update(block)
        report["dump_gib"] = round(dump.stat().st_size / 2**30, 2)
        Path(bundle).chmod(0o700)
        os.chown(bundle, 0, 0)
        Path(dump).chmod(0o644)
        for name, body in (("pre-data.sql", pre), ("post-data.sql", post)):
            (bundle / name).write_bytes(body)
            Path(bundle / name).chmod(0o600)
        approval = {
            "version": 1,
            "backup_sha256": digest.hexdigest(),
            "pre_data_sha256": hashlib.sha256(pre).hexdigest(),
            "post_data_sha256": hashlib.sha256(post).hexdigest(),
        }
        (bundle / "approval.json").write_text(json.dumps(approval))
        Path(bundle / "approval.json").chmod(0o600)
        # Restore under the hosted runtime's postgres container limits (4 GiB, 4 CPUs, no network).
        os.chown(restore_data, UID, UID)
        script = (
            "initdb -D /var/lib/postgresql/data --auth-local=trust --auth-host=reject -U postgres "
            "&& exec postgres -D /var/lib/postgresql/data -c listen_addresses='' "
            "-c unix_socket_directories=/run/postgresql -c unix_socket_permissions=0777"
        )
        restore_args = [
            "--network=none",
            "--user",
            f"{UID}:{UID}",
            "--memory",
            str(4 * 2**30),
            "--memory-swap",
            str(4 * 2**30),
            "--cpus",
            str(cpus),
            "--entrypoint",
            "/bin/sh",
            "--tmpfs",
            f"/run/postgresql:rw,nosuid,nodev,noexec,size=1m,uid={UID},gid={UID},mode=0711",
            "-v",
            f"{restore_data}:/var/lib/postgresql/data",
            "-v",
            f"{dump}:/restore/backup.dump:ro",
        ]
        with timer("restore_container_start"):
            sh("docker", "run", "-d", "--name", "restore", *restore_args, IMAGE, "-ec", script)
            for _ in range(120):
                if (
                    subprocess.run(
                        ["docker", "exec", "-u", "postgres", "restore", "pg_isready", "-q"], check=False
                    ).returncode
                    == 0
                ):
                    break
                time.sleep(2)
        transport = Transport("restore", calls)
        transport.run("psql", ["-X", "-q", "-d", "postgres", "-c", "CREATE DATABASE btmt_grow_perf TEMPLATE template0"])
        with timer("restore_total"):
            evidence = restore_approved(transport, SimpleNamespace(backup_sha256=approval["backup_sha256"]), bundle)
        report["row_counts"] = {k: v for k, v in evidence["row_counts"].items() if v}
        report["restored_db_gib"] = round(
            int(
                transport.run(
                    "psql", ["-X", "-Atq", "-d", "btmt_grow_perf", "-c", "SELECT pg_database_size('btmt_grow_perf')"]
                )
            )
            / 2**30,
            2,
        )
        if search:
            with timer("search_rebuild"):
                transport.run(
                    "psql",
                    [
                        "-X",
                        "-q",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-d",
                        "btmt_grow_perf",
                        "-c",
                        "INSERT INTO grow_song_search (track_id, document, title_key, has_genre, playable, rank_score) "
                        "SELECT uuid, to_tsvector('simple', title), lower(title), true, true, 0 FROM the_music_tree_genre_kit_track; "
                        "CREATE INDEX grow_song_search_doc_idx ON grow_song_search USING gin (document);",
                    ],
                )
            report["restored_db_with_search_gib"] = round(
                int(
                    transport.run(
                        "psql",
                        ["-X", "-Atq", "-d", "btmt_grow_perf", "-c", "SELECT pg_database_size('btmt_grow_perf')"],
                    )
                )
                / 2**30,
                2,
            )
        report["oom_killed"] = sh("docker", "inspect", "-f", "{{.State.OOMKilled}}", "restore").strip()
        report["call_timings_s"] = calls
        report["status"] = "ok"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = repr(error)[-3000:]
    finally:
        sampler.stop.set()
        sampler.join()
        report["timings_s"] = dict(timer)
        report["resources"] = sampler.summary()
        report["oom_dmesg"] = subprocess.run(
            "dmesg | grep -ci 'out of memory'", shell=True, text=True, capture_output=True, check=False
        ).stdout.strip()
        (work / "samples.json").write_text(json.dumps(sampler.rows))
        subprocess.run(["docker", "rm", "-f", "restore", "gen"], capture_output=True, check=False)
    print(json.dumps(report, indent=1))
    Path(os.environ.get("REPORT", work / "report.json")).write_text(json.dumps(report, indent=1))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
