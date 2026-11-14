"""Opt-in SSH checks against the shared Docker/Podman Compose stack."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import time
import uuid

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("runtime", ["docker", "podman"])
def test_ssh_clone_push_rejection_and_restart(tmp_path, runtime):
    if (not any(os.getenv(key) == "1" for key in ("AEGIS_CONTAINER_SMOKE", "AEGIS_DOCKER_SMOKE"))
            or shutil.which(runtime) is None):
        pytest.skip("Set AEGIS_CONTAINER_SMOKE=1 with Docker or Podman and a Compose provider installed")
    with socket.socket() as web_sock, socket.socket() as ssh_sock:
        web_sock.bind(("127.0.0.1", 0))
        ssh_sock.bind(("127.0.0.1", 0))
        web_port, ssh_port = web_sock.getsockname()[1], ssh_sock.getsockname()[1]
    key = tmp_path / "identity"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    env = {**os.environ, "AEGIS_AUTHORIZED_KEYS": str(key) + ".pub",
           "AEGIS_PORT": str(web_port), "AEGIS_BIND_ADDRESS": "127.0.0.1",
           "AEGIS_GIT_PORT": str(ssh_port), "AEGIS_GIT_BIND_ADDRESS": "127.0.0.1",
           "BYOM_OFFLINE": "true", "AUTO_SYNC": "false", "COMPANIES_DIR": "/app/tests/fixtures/companies"}
    for name in ("MONGODB_URI", "LINKUP_API_KEY", "DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID",
                 "MLFLOW_TRACKING_URI", "GITHUB_TOKEN", "CONFLUENCE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN"):
        env[name] = ""
    env["GIT_SSH_COMMAND"] = shlex.join([
        "ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={tmp_path / 'known_hosts'}"])
    compose = [runtime, "compose", "-p", "aegis-git-test-" + uuid.uuid4().hex[:10],
               "-f", str(ROOT / "compose.yaml"), "--profile", "git"]
    remote = f"ssh://git@127.0.0.1:{ssh_port}/demo.git"
    web_url = f"http://127.0.0.1:{web_port}/healthz"

    def run(args, **kwargs):
        return subprocess.run(args, env=env, capture_output=True, text=True, **kwargs)

    def ready():
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = run(["git", "ls-remote", remote], timeout=5)
            if result.returncode == 0:
                try:
                    if httpx.get(web_url, timeout=2).json() == {"status": "ok"}:
                        return result.stdout
                except (httpx.HTTPError, ValueError):
                    pass
            time.sleep(0.25)
        logs = run([*compose, "logs"])
        pytest.fail(f"Shared stack did not become ready: {logs.stdout}\n{logs.stderr}")

    try:
        configured = run([*compose, "config"], timeout=30)
        assert configured.returncode == 0, configured.stderr
        started = run([*compose, "up", "--build", "-d"], timeout=900)
        assert started.returncode == 0, started.stdout + started.stderr
        ready()
        work = tmp_path / "client"
        result = run(["git", "clone", remote, str(work)], timeout=30)
        assert result.returncode == 0, result.stderr
        for name, value in (("user.name", "Smoke"), ("user.email", "smoke@localhost")):
            assert run(["git", "config", name, value], cwd=work).returncode == 0
        (work / "README.md").write_text("Safe unrelated change\n")
        assert run(["git", "add", "."], cwd=work).returncode == 0
        assert run(["git", "commit", "-m", "unrelated change"], cwd=work).returncode == 0
        accepted = run(["git", "push"], cwd=work, timeout=90)
        assert accepted.returncode == 0, accepted.stderr
        before = ready()
        with (work / "app/main.py").open("a") as stream:
            stream.write("\ndef submit_customer(customer):\n"
                         "    return requests.post('https://external.service', json=customer)\n")
        assert run(["git", "add", "."], cwd=work).returncode == 0
        assert run(["git", "commit", "-m", "regression"], cwd=work).returncode == 0
        rejected = run(["git", "push", "--no-verify"], cwd=work, timeout=90)
        assert rejected.returncode != 0 and "PII-01" in rejected.stderr
        assert ready() == before
        reports = run([*compose, "exec", "-T", "git", "ls", "/var/lib/aegis/reports"])
        assert reports.returncode == 0 and ".accepted.json" in reports.stdout
        assert run([*compose, "restart"], timeout=30).returncode == 0
        assert ready() == before  # host identity and accepted history both persist
    finally:
        run([*compose, "down", "--volumes"], timeout=60)
