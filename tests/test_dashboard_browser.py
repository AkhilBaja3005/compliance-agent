"""Real Chromium + live Uvicorn checks. Opt in with GRAPHITE_BROWSER_TESTS=1."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv("GRAPHITE_BROWSER_TESTS") != "1", reason="Set GRAPHITE_BROWSER_TESTS=1 and install Playwright Chromium")
ROOT = Path(__file__).resolve().parents[1]
A, B, C = "company_a_finscore", "company_b_voxgen", "company_c_medassist"


@contextmanager
def live_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "BYOM_OFFLINE": "true", "AUTO_SYNC": "false",
           "GRAPHITE_DASHBOARD_DB": str(tmp_path / "live.sqlite3"),
           "GRAPHITE_HISTORY_FILE": str(tmp_path / "history.json"),
           "COMPANIES_DIR": str(ROOT / "tests/fixtures/companies")}
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.api:app", "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if httpx.get(url + "/healthz", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                time.sleep(.05)
            else:
                pytest.fail("Browser test server did not start")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
def workspace(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with live_server(tmp_path) as url, playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            yield page, url, playwright.expect
            assert errors == []
        finally:
            browser.close()


def test_both_pages_audits_filters_evidence_refresh_and_company_selection(workspace, tmp_path):
    page, url, expect = workspace
    report_requests = []
    page.on("request", lambda request: report_requests.append(request.url) if "/reports/" in request.url else None)
    page.goto(url + f"/dashboard/overview?company={B}")
    expect(page).to_have_title("Graphite · Compliance dashboard")
    expect(page.locator(".brand img")).to_have_attribute("src", "/dashboard/assets/graphite_report_logo.png")
    assert page.locator(".brand img").evaluate("img => img.complete && img.naturalWidth > 0")
    expect(page.get_by_role("link", name="API documentation")).to_have_count(0)
    expect(page.locator(".rail-footer p")).to_have_text("EU · AI governance")
    assert page.locator("body").evaluate("node => getComputedStyle(node).backgroundColor") == "rgb(229, 244, 255)"
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")
    expect(page.locator("#schedule-frequency")).to_have_value("daily")
    expect(page.locator("#schedule-enabled")).not_to_be_checked()
    expect(page.locator("#run-audit")).to_be_enabled()
    page.locator("#run-audit").click()
    expect(page.locator("#overview-content")).to_be_visible(timeout=20000)
    assert int(page.locator("#confirmed-count").inner_text()) > 0
    expect(page.locator("#engines")).to_contain_text("offline-fallback")
    expect(page.locator("#assessment")).not_to_contain_text("none available")
    first_requests = len(report_requests)
    page.wait_for_timeout(5500)
    assert len(report_requests) == first_requests  # unchanged reports are not downloaded on each poll
    page.screenshot(path=str(tmp_path / "leadership.png"), full_page=True)

    page.locator("#findings-link").click()
    expect(page).to_have_url(url + f"/dashboard/findings?company={B}")
    expect(page.locator("#findings-content")).to_be_visible()
    expect(page.locator("#company")).to_have_value(B)
    all_count = page.locator(".finding").count()
    assert all_count > 0
    page.locator("#filter-status").select_option("CONFIRMED_VIOLATION")
    assert 0 < page.locator(".finding").count() <= all_count
    page.locator("#filter-text").fill("not-a-real-finding-928347")
    expect(page.locator(".no-results")).to_be_visible()
    page.locator("#clear-filters").click()
    assert page.locator(".finding").count() == all_count
    # Exercise each select filter against a real available value.
    for control in ("filter-severity", "filter-system", "filter-jurisdiction"):
        options = page.locator(f"#{control} option").evaluate_all("nodes => nodes.map(n => n.value).filter(Boolean)")
        for option in options:
            page.locator(f"#{control}").select_option(option)
            if page.locator(".finding").count():
                break
        assert page.locator(".finding").count() > 0
        page.locator("#clear-filters").click()
    finding = page.locator(".finding").filter(has=page.locator(".evidence")).first
    finding.locator("summary").click()
    expect(finding.locator(".evidence").first).to_be_visible()
    expect(finding.locator(".evidence pre").first).not_to_be_empty()
    expect(finding.locator(".finding-body")).to_contain_text("Remediation steps")
    expect(finding.locator(".finding-body")).to_contain_text("Confidence")
    page.wait_for_timeout(5500)
    expect(finding).to_have_attribute("open", "")
    page.screenshot(path=str(tmp_path / "engineering.png"), full_page=True)

    page.locator("#company").select_option(A)
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")
    page.locator("#overview-link").click()
    expect(page).to_have_url(url + f"/dashboard/overview?company={A}")
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")


def test_settings_failures_previous_report_and_connection_recovery(workspace, tmp_path):
    page, url, expect = workspace
    # A synchronous caller publishes to exactly the same dashboard storage.
    result = httpx.post(url + "/audit/run", json={"company_id": A}, timeout=20).json()
    page.goto(url + f"/dashboard/overview?company={A}")
    expect(page.locator("#overview-content")).to_be_visible()
    count = page.locator("#confirmed-count").inner_text()
    page.locator("#settings-panel summary").click()
    page.locator("#github-source").fill("/missing/repository")
    expect(page.locator("#run-audit")).to_be_disabled()
    page.locator("#save-settings").click()
    expect(page.locator("#settings-message")).to_contain_text("Settings saved")
    expect(page.locator("#run-audit")).to_be_enabled()
    page.locator("#run-audit").click()
    expect(page.locator("#activity")).to_contain_text("failed", timeout=15000)
    expect(page.locator("#overview-content")).to_be_visible()
    expect(page.locator("#confirmed-count")).to_have_text(count)
    assert httpx.get(url + f"/dashboard/api/companies/{A}/snapshot").json()["latest_report"]["report_id"] == result["report_id"]

    page.locator("#github-source").fill("")
    page.locator("#schedule-enabled").check()
    page.locator("#schedule-frequency").select_option("hourly")
    page.locator("#save-settings").click()
    expect(page.locator("#schedule-summary")).to_contain_text("hourly")
    snapshot = httpx.get(url + f"/dashboard/api/companies/{A}/snapshot").json()
    assert snapshot["next_scheduled_run"] and snapshot["latest_job"]["state"] == "failed"

    page.route("**/snapshot", lambda route: route.abort("failed"))
    expect(page.locator("#connection")).to_have_text("Disconnected", timeout=10000)
    expect(page.locator("#overview-content")).to_be_visible()
    expect(page.locator("#confirmed-count")).to_have_text(count)
    page.unroute("**/snapshot")
    expect(page.locator("#connection")).to_have_text("Live updates", timeout=10000)
    expect(page.locator("#notice")).to_be_hidden()

    page.locator("#company").select_option(C)
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")
    if page.locator("#settings-panel").get_attribute("open") is None:
        page.locator("#settings-panel summary").click()
    page.locator("#github-source").fill("/missing/repository")
    page.locator("#save-settings").click()
    expect(page.locator("#settings-message")).to_contain_text("Settings saved")
    page.locator("#run-audit").click()
    expect(page.locator("#empty-title")).to_have_text("Audit failed", timeout=15000)
    expect(page.locator("#overview-content")).to_be_hidden()

    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(tmp_path / "mobile-empty.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator("#company").select_option(A)
    expect(page.locator("#overview-content")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(tmp_path / "mobile-overview.png"), full_page=True)


def test_late_responses_after_company_switch_are_discarded(workspace):
    page, url, expect = workspace
    httpx.post(url + "/audit/run", json={"company_id": B}, timeout=20).raise_for_status()
    page.goto(url + f"/dashboard/overview?company={A}")
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")
    held = []

    def hold(route):
        held.append((route, route.fetch()))

    pattern = f"**/companies/{B}/reports/*"
    page.route(pattern, hold)
    page.locator("#company").select_option(B)
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert held
    page.locator("#company").select_option(A)
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")
    for route, response in held:
        route.fulfill(response=response)
    page.wait_for_timeout(200)
    expect(page.locator("#company")).to_have_value(A)
    expect(page.locator("#overview-content")).to_be_hidden()
    expect(page.locator("#empty-title")).to_have_text("No assessment yet")


def test_browser_recovers_from_initial_loading_failure(workspace):
    page, url, expect = workspace
    page.route("**/companies", lambda route: route.abort("failed"))
    page.goto(url + "/dashboard/overview")
    expect(page.locator("#empty-title")).to_have_text("Workspace disconnected")
    page.unroute("**/companies")
    expect(page.locator("#empty-title")).to_have_text("No assessment yet", timeout=10000)
    expect(page.locator("#run-audit")).to_be_enabled()
