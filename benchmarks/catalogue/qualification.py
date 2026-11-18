"""Prove the hosted container flags isolate network, filesystem and privileges (disposable runner only)."""

import os
import subprocess
import sys
import unittest

IMAGE = "alpine:3.23"
FLAGS = [
    "--network=none",
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges:true",
    "--memory=64m",
    "--memory-swap=64m",
    "--pids-limit=32",
    "--cpus=1",
    "--user=70:70",
    "--label=btmt.grow-perf.invocation=qualification",
]


def run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            *FLAGS,
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=8m",
            IMAGE,
            "sh",
            "-c",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


class HostedIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "linux" or os.geteuid() != 0:
            raise RuntimeError("qualification requires Linux root")
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
            raise RuntimeError("qualification may run only on a disposable GitHub-hosted runner")
        subprocess.run(["docker", "pull", "-q", IMAGE], check=True, capture_output=True, timeout=120)

    def test_only_loopback_exists(self):
        result = run("ls /sys/class/net")
        self.assertEqual(result.stdout.split(), ["lo"], result.stderr)

    def test_no_route_to_the_host_or_internet(self):
        for target in ("1.1.1.1", "172.17.0.1", "127.0.0.1:2375"):
            self.assertNotEqual(run(f"wget -q -T 2 -O /dev/null http://{target}/").returncode, 0, target)

    def test_root_filesystem_is_read_only(self):
        self.assertNotEqual(run("touch /etc/x").returncode, 0)
        self.assertEqual(run("touch /tmp/x").returncode, 0)
        self.assertNotEqual(run("cp /bin/sh /tmp/s && /tmp/s -c true").returncode, 0, "tmpfs must be noexec")

    def test_no_capabilities_and_no_privilege_gain(self):
        result = run("grep -E '^(CapEff|NoNewPrivs)' /proc/self/status")
        self.assertIn("CapEff:\t0000000000000000", result.stdout)
        self.assertIn("NoNewPrivs:\t1", result.stdout)
        self.assertNotEqual(run("mount -t tmpfs none /tmp").returncode, 0)

    def test_process_limit_is_enforced(self):
        self.assertNotEqual(run("i=0; while [ $i -lt 200 ]; do sleep 5 & i=$((i+1)); done; wait").returncode, 0)


if __name__ == "__main__":
    unittest.main()
