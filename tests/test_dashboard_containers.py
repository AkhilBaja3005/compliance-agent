"""Optional smoke tests for the shared Compose stack with each installed runtime."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import uuid

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("runtime", ["docker", "podman"])
def test_container_health_audit_and_persistence(runtime):
    if os.getenv("GRAPHITE_CONTAINER_SMOKE") != "1" or not shutil.which(runtime):
        pytest.skip("Set GRAPHITE_CONTAINER_SMOKE=1 with Docker or Podman and its Compose provider installed")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    project = "graphite-dashboard-test-" + uuid.uuid4().hex[:10]
    compose = [runtime, "compose", "-p", project, "-f", str(ROOT / "compose.yaml")]
    env = {**os.environ, "GRAPHITE_PORT": str(port), "GRAPHITE_BIND_ADDRESS": "127.0.0.1",
           "BYOM_OFFLINE": "true", "GRAPHITE_AUTH_DISABLED": "true", "AUTO_SYNC": "false", "COMPANIES_DIR": "/app/tests/fixtures/companies"}
    for key in ("MONGODB_URI", "LINKUP_API_KEY", "DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID",
                "MLFLOW_TRACKING_URI", "GITHUB_TOKEN", "CONFLUENCE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN"):
        env[key] = ""

    def run(*args, timeout=60):
        return subprocess.run([*compose, *args], env=env, cwd=ROOT, capture_output=True, text=True, timeout=timeout)

    url = f"http://127.0.0.1:{port}"

    def healthy():
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if httpx.get(url + "/healthz", timeout=2).json() == {"status": "ok"}:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(.25)
        pytest.fail("Container startup failed: " + run("logs").stdout)

    try:
        config = run("config")
        assert config.returncode == 0, config.stderr
        started = run("up", "--build", "-d", timeout=900)
        assert started.returncode == 0, started.stdout + started.stderr
        healthy()
        for page in ("overview", "findings"):
            assert httpx.get(url + f"/dashboard/{page}").status_code == 200
        logo = httpx.get(url + "/dashboard/assets/graphite_report_logo.png")
        assert logo.status_code == 200
        assert logo.headers["content-type"] == "image/png"
        assert logo.content == (ROOT / "assets" / "graphite_report_logo.png").read_bytes()
        base = url + "/dashboard/api/companies/company_a_finscore"
        assert httpx.get(base + "/snapshot").json()["latest_report"] is None
        settings = {"sources": {}, "schedule": {"enabled": True, "frequency": "weekly"}}
        assert httpx.put(base + "/settings", json=settings).status_code == 200
        response = httpx.post(base + "/runs")
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            job = httpx.get(base + f"/runs/{job_id}").json()
            if job["state"] in ("succeeded", "failed"):
                break
            time.sleep(.25)
        assert job["state"] == "succeeded", job
        before = httpx.get(base + "/snapshot").json()
        assert before["latest_report"]["report_id"] == job["report_id"]
        check = run("exec", "-T", "graphite", "python", "-c",
                    "import os; from pathlib import Path; assert os.getuid() != 0; assert Path('/var/lib/graphite/finding-history.json').is_file()")
        assert check.returncode == 0, check.stderr
        # Invoke the exact configured health-check command, independent of its timer.
        check = run("exec", "-T", "graphite", "python", "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()")
        assert check.returncode == 0, check.stderr
        assert run("restart", "graphite").returncode == 0
        healthy()
        after = httpx.get(base + "/snapshot").json()
        assert after["latest_report"]["report_id"] == before["latest_report"]["report_id"]
        assert after["settings"] == before["settings"]
        assert after["next_scheduled_run"] == before["next_scheduled_run"]
        assert httpx.get(base + f"/reports/{job['report_id']}").status_code == 200
    finally:
        run("down", "--volumes", timeout=90)
