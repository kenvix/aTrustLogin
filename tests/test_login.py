import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from main import ATrustLogin


class ClientPermissionTests(unittest.TestCase):
    def setUp(self):
        self.login = ATrustLogin.__new__(ATrustLogin)
        self.login.driver = MagicMock()
        self.login.portal_address = "https://vpn.example.test:8443/login?lang=zh#auth"

    def test_grants_only_loopback_access_to_portal_origin(self):
        self.assertTrue(self.login.configure_client_access())
        self.login.driver.execute_cdp_cmd.assert_called_once_with(
            "Browser.setPermission",
            {"permission": {"name": "loopback-network"}, "setting": "granted",
             "origin": "https://vpn.example.test:8443"},
        )

    def test_uses_legacy_permission_when_loopback_is_unsupported(self):
        self.login.driver.execute_cdp_cmd.side_effect = [
            WebDriverException("Invalid PermissionDescriptor name: loopback-network"), {},
        ]
        self.assertTrue(self.login.configure_client_access())
        calls = self.login.driver.execute_cdp_cmd.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].args[1]["permission"]["name"], "local-network-access")
        self.assertEqual(calls[1].args[1]["origin"], "https://vpn.example.test:8443")

    def test_unsupported_browser_can_continue(self):
        self.login.driver.execute_cdp_cmd.side_effect = WebDriverException("unsupported")
        with patch("main.logger.warning") as warning:
            self.assertFalse(self.login.configure_client_access())
        warning.assert_called_once()

    def test_origin_preserves_ipv6_and_port(self):
        self.login.portal_address = "https://[::1]:8443/login"
        self.login.configure_client_access()
        self.assertEqual(self.login.driver.execute_cdp_cmd.call_args.args[1]["origin"],
                         "https://[::1]:8443")

    def test_origin_omits_userinfo_and_path(self):
        self.login.portal_address = "https://example-user:example-password@vpn.example.test/login"
        self.login.configure_client_access()
        self.assertEqual(self.login.driver.execute_cdp_cmd.call_args.args[1]["origin"],
                         "https://vpn.example.test")

    def test_invalid_portal_never_grants_global_permissions(self):
        for address in ("", "vpn.example.test", "file:///tmp/portal.html", "https://"):
            with self.subTest(address=address):
                self.login.portal_address = address
                with self.assertRaises(ValueError):
                    self.login.configure_client_access()
        self.login.driver.execute_cdp_cmd.assert_not_called()

    def test_all_browser_startup_modes_configure_access_before_navigation(self):
        for driver_type, container_mode in (("chrome", False), ("edge", False), ("chrome", True)):
            with self.subTest(driver_type=driver_type, container_mode=container_mode):
                driver = MagicMock()
                process = MagicMock()
                process.poll.return_value = None
                with tempfile.TemporaryDirectory() as data_dir, \
                        patch("main.webdriver.Chrome", return_value=driver), \
                        patch("main.webdriver.Edge", return_value=driver), \
                        patch("main.subprocess.Popen", return_value=process), \
                        patch("main.urllib.request.urlopen"), \
                        patch("builtins.open", MagicMock()):
                    login = ATrustLogin("https://vpn.example.test", driver_type=driver_type,
                                       container_mode=container_mode, data_dir=data_dir)
                    driver.execute_cdp_cmd.assert_called_once()
                    driver.get.assert_not_called()
                    login.close()


class PortalHandler(BaseHTTPRequestHandler):
    html = "<!doctype html><title>Local test portal</title>"

    def do_GET(self):
        body = b"client-ready" if self.path == "/ping" else self.html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(os.environ.get("ATRUST_BROWSER_TESTS") == "1",
                     "Set ATRUST_BROWSER_TESTS=1 to run Chrome integration tests")
class LoginBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers = []
        for _ in range(2):
            server = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.servers.append(server)
            cls.addClassCleanup(server.server_close)
            cls.addClassCleanup(server.shutdown)
        cls.origin = f"http://127.0.0.1:{cls.servers[0].server_port}"
        cls.client_url = f"http://127.0.0.1:{cls.servers[1].server_port}/ping"
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--enable-features=LocalNetworkAccessChecks")
        options.add_argument(f"--ip-address-space-overrides=127.0.0.1:{cls.servers[0].server_port}=public")
        binary = os.environ.get("CHROME_BINARY") or shutil.which("google-chrome") or shutil.which("chromium")
        if binary:
            options.binary_location = binary
        cls.driver = webdriver.Chrome(service=Service(os.environ.get("CHROMEDRIVER")), options=options)
        cls.addClassCleanup(cls.driver.quit)
        cls.driver.set_script_timeout(10)

    def setUp(self):
        self.driver.execute_cdp_cmd("Browser.resetPermissions", {})
        self.login = ATrustLogin.__new__(ATrustLogin)
        self.login.driver = self.driver
        self.login.portal_address = self.origin
        self.login.wait = WebDriverWait(self.driver, 2, poll_frequency=0.05)
        self.login.delay_input = lambda: None
        self.login.delay_loading = lambda: None
        self.login.initialized = True
        self.login.must_be_logged_keywords = ["app_center"]
        self.login.update_storage = MagicMock()

    def load_page(self, checkbox="", prefix="", fields=""):
        PortalHandler.html = f"""<!doctype html><meta charset="utf-8">
            {prefix}<div id="sangfor_main_auth_container"><form class="login-panel">
            {fields}<input id="username" placeholder="账号"><input id="password" type="password" placeholder="密码">
            {checkbox}<button type="submit">登录</button></form></div>
            <script>window.changes = 0;
            document.addEventListener('change', e => {{if (e.target.type === 'checkbox') window.changes++;}});
            document.querySelector('form').onsubmit = e => {{e.preventDefault();
                const box = document.getElementById('agreement');
                if ((!box || box.checked) && document.getElementById('username').value === 'test-user'
                    && document.getElementById('password').value === 'test-password') location.hash = 'app_center';
            }};</script>"""
        self.driver.get(self.origin)

    def fill_credentials(self):
        self.login.enter_credentials("test-user", "test-password")
        self.assertEqual(self.driver.find_element(By.ID, "username").get_attribute("value"), "test-user")
        self.assertEqual(self.driver.find_element(By.ID, "password").get_attribute("value"), "test-password")

    def test_native_checkbox(self):
        self.load_page('<input type="checkbox" id="agreement">')
        self.fill_credentials()
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())

    def test_hidden_checkbox_with_wrapping_label(self):
        self.load_page('<label><input type="checkbox" id="agreement" style="display:none">Accept</label>')
        self.fill_credentials()
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())
        self.assertEqual(self.driver.execute_script("return window.changes"), 1)

    def test_hidden_checkbox_with_external_label(self):
        self.load_page('<input type="checkbox" id="agreement" style="display:none"><label for="agreement">Accept</label>')
        self.fill_credentials()
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())

    def test_styled_zero_size_checkbox(self):
        self.load_page('<label><input type="checkbox" id="agreement" style="opacity:0;width:0;height:0;position:absolute"><span>Accept</span></label>')
        self.fill_credentials()
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())

    def test_checked_checkbox_remains_selected(self):
        self.load_page('<label><input type="checkbox" id="agreement" checked style="display:none">Accept</label>')
        self.fill_credentials()
        self.fill_credentials()
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())
        self.assertEqual(self.driver.execute_script("return window.changes"), 0)

    def test_checkbox_search_is_scoped_to_login_container(self):
        self.load_page('<label><input type="checkbox" id="agreement" style="display:none">Accept</label>',
                       prefix='<input type="checkbox" id="outside">')
        self.fill_credentials()
        self.assertFalse(self.driver.find_element(By.ID, "outside").is_selected())
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())

    def test_hidden_template_and_disabled_checkboxes_are_skipped(self):
        self.load_page('<div style="display:none"><label><input type="checkbox" id="hidden">Hidden</label></div>'
                       '<input type="checkbox" id="disabled" disabled><input type="checkbox" id="agreement">')
        self.fill_credentials()
        self.assertFalse(self.driver.find_element(By.ID, "hidden").is_selected())
        self.assertFalse(self.driver.find_element(By.ID, "disabled").is_selected())
        self.assertTrue(self.driver.find_element(By.ID, "agreement").is_selected())

    def test_optional_checkbox_can_be_absent(self):
        self.load_page()
        self.fill_credentials()

    def test_hidden_and_disabled_credential_fields_are_skipped(self):
        self.load_page(fields='<div style="display:none"><input placeholder="账号"><input placeholder="密码"></div>'
                       '<input placeholder="account" disabled><input type="hidden" placeholder="password">')
        self.fill_credentials()

    def test_login_completes_on_local_test_portal(self):
        self.load_page('<label><input type="checkbox" id="agreement" style="display:none">Accept</label>')
        self.assertTrue(self.login.login("test-user", "test-password", None))
        self.login.update_storage.assert_called_once()

    def permission(self):
        return self.driver.execute_async_script("""
            const done = arguments[arguments.length - 1];
            (async () => {
                for (const name of ['loopback-network', 'local-network-access']) {
                    try { const permission = await navigator.permissions.query({name});
                          done({name, state: permission.state}); return; } catch (error) {}
                }
                done(null);
            })();
        """)

    def test_permission_is_granted_before_navigation_and_scoped_to_portal(self):
        self.assertTrue(self.login.configure_client_access())
        self.load_page()
        self.assertEqual(self.permission()["state"], "granted")
        self.driver.get(self.origin.replace("127.0.0.1", "localhost"))
        self.assertEqual(self.permission()["state"], "prompt")

    def test_local_client_request_succeeds_with_permission(self):
        self.load_page()
        permission = self.permission()
        self.assertIsNotNone(permission)
        self.driver.execute_cdp_cmd("Browser.setPermission", {
            "permission": {"name": permission["name"]}, "setting": "denied", "origin": self.origin,
        })
        script = """const done = arguments[arguments.length - 1];
            fetch(arguments[0], {signal: AbortSignal.timeout(5000)})
            .then(response => response.text()).then(done).catch(() => done('blocked'));"""
        self.assertEqual(self.driver.execute_async_script(script, self.client_url), "blocked")
        self.assertTrue(self.login.configure_client_access())
        self.assertEqual(self.driver.execute_async_script(script, self.client_url), "client-ready")


if __name__ == "__main__":
    unittest.main()
