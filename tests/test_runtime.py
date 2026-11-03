import io
import os
import pickle
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fire import Fire
from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from browser_log import BrowserLog
from launcher import build_command
from main import ATrustLogin, ATrustLoginStorage, main


def login_stub():
    login = ATrustLogin.__new__(ATrustLogin)
    login.driver = MagicMock()
    login.portal_address = "https://vpn.example.test/"
    login.portal_host = "vpn.example.test"
    login.driver.current_url = login.portal_address
    login.cookie_tid = None
    login.cookie_sig = None
    login.must_be_logged_keywords = ["app_center", "user_info", "app_apply", "device_manage"]
    return login


class RuntimeTests(unittest.TestCase):
    def test_cli_allows_omitting_credentials(self):
        with patch("main.ATrustLogin") as cls:
            cls.return_value.initialized = False
            cls.return_value.login.return_value = True
            Fire(main, command=["--portal_address=https://vpn.example.test", "--wait_atrust=False", "--keepalive=0"])
            cls.return_value.login.assert_called_once_with(username=None, password=None, totp_key=None)
            cls.return_value.close.assert_called_once()

    def test_partial_credentials_are_rejected_before_browser_start(self):
        for kwargs in ({"username": "test"}, {"password": "test"}):
            with self.subTest(kwargs=kwargs), patch("main.webdriver.Chrome") as driver:
                with self.assertRaisesRegex(ValueError, "both"):
                    main("https://vpn.example.test", wait_atrust=False, **kwargs)
                driver.assert_not_called()

    def test_invalid_timeouts_are_rejected_before_browser_start(self):
        for kwargs in ({"login_timeout": 0}, {"client_timeout": -1}):
            with self.subTest(kwargs=kwargs), patch("main.webdriver.Chrome") as driver:
                with self.assertRaises(ValueError):
                    main("https://vpn.example.test", wait_atrust=False, **kwargs)
                driver.assert_not_called()

    def test_login_failure_closes_browser(self):
        with patch("main.ATrustLogin") as cls:
            cls.return_value.initialized = False
            cls.return_value.login.side_effect = RuntimeError("test failure")
            with self.assertRaises(RuntimeError):
                main("https://vpn.example.test", wait_atrust=False, keepalive=0)
            cls.return_value.close.assert_called_once()

    def test_closed_session_exits_for_process_restart(self):
        with patch("main.ATrustLogin") as cls:
            cls.return_value.initialized = False
            cls.return_value.login.side_effect = InvalidSessionIdException()
            with self.assertRaises(InvalidSessionIdException):
                main("https://vpn.example.test", wait_atrust=False)
            cls.return_value.close.assert_called_once()

    def test_retry_logs_do_not_include_exception_secrets(self):
        with patch("main.ATrustLogin") as cls, patch("main.logger.error") as error:
            cls.return_value.initialized = False
            cls.return_value.login.side_effect = [RuntimeError("test-sensitive-value"), KeyboardInterrupt()]
            with self.assertRaises(KeyboardInterrupt):
                main("https://vpn.example.test", wait_atrust=False)
            self.assertNotIn("test-sensitive-value", str(error.call_args_list))
            cls.return_value.close.assert_called_once()

    def test_native_startup_failure_cleans_profile(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("main.tempfile.TemporaryDirectory") as profile, \
                patch("main.webdriver.Chrome", side_effect=WebDriverException("test failure")):
            profile.return_value.name = directory
            with self.assertRaises(WebDriverException):
                ATrustLogin("https://vpn.example.test", data_dir=directory, driver_type="chrome")
            profile.return_value.cleanup.assert_called_once()

    def test_attached_driver_failure_stops_browser_and_log(self):
        process = MagicMock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
                patch("main.subprocess.Popen", return_value=process), \
                patch("main.BrowserLog") as log, \
                patch("main.urllib.request.urlopen"), \
                patch("main.webdriver.Chrome", side_effect=WebDriverException("test failure")):
            with self.assertRaises(WebDriverException):
                ATrustLogin("https://vpn.example.test", data_dir=directory, container_mode=True)
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            log.return_value.close.assert_called_once()

    def test_devtools_startup_wait_is_bounded(self):
        process = MagicMock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
                patch("main.subprocess.Popen", return_value=process), \
                patch("main.BrowserLog"), \
                patch("main.urllib.request.urlopen", side_effect=OSError()), \
                patch("main.time.monotonic", side_effect=[0, 61]), \
                patch("main.webdriver.Chrome") as driver:
            with self.assertRaisesRegex(TimeoutError, "DevTools"):
                ATrustLogin("https://vpn.example.test", data_dir=directory, container_mode=True)
            driver.assert_not_called()
            process.terminate.assert_called_once()

    def test_cleanup_continues_after_webdriver_failure(self):
        login = login_stub()
        login.driver.quit.side_effect = WebDriverException("test failure")
        login.chrome_process = MagicMock()
        login.chrome_process.poll.return_value = None
        login.chrome_process.wait.side_effect = [subprocess.TimeoutExpired("chrome", 5), 0]
        login._browser_log = MagicMock()
        login._profile = MagicMock()
        process, log, profile = login.chrome_process, login._browser_log, login._profile
        login.close()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        log.close.assert_called_once()
        profile.cleanup.assert_called_once()
        self.assertIsNone(login.driver)

    def test_browser_cache_limits_apply_to_chrome_and_edge(self):
        for platform_name, expected in (("Linux", "Chrome"), ("Darwin", "Chrome"), ("Windows", "Edge")):
            with self.subTest(platform=platform_name), tempfile.TemporaryDirectory() as directory, \
                    patch("main.platform.system", return_value=platform_name), \
                    patch("main.webdriver.Chrome") as chrome, patch("main.webdriver.Edge") as edge:
                login = ATrustLogin("https://vpn.example.test", data_dir=directory)
                selected = chrome if expected == "Chrome" else edge
                options = selected.call_args.kwargs["options"]
                self.assertIn("--disk-cache-size=268435456", options.arguments)
                profile_path = login._profile.name
                login.close()
                self.assertFalse(Path(profile_path).exists())

    def test_browser_output_rotates_with_long_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            log = BrowserLog(io.BytesIO(b"x" * 200000), Path(directory) / "chrome.log",
                             max_bytes=16384, backup_count=2)
            log.close()
            self.assertFalse(log.thread.is_alive())
            files = list(Path(directory).glob("chrome.log*"))
            self.assertEqual(len(files), 3)
            self.assertTrue(all(path.stat().st_size <= 16384 for path in files))

    def test_client_wait_accepts_listening_socket(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            ATrustLogin.wait_for_port(server.getsockname()[1], host="127.0.0.1", timeout=1)

    def test_client_wait_timeout_has_diagnostic_message(self):
        with patch("main.socket.create_connection", side_effect=ConnectionRefusedError()), \
                patch("main.time.monotonic", side_effect=[0, 0, 1, 1]), patch("main.time.sleep"):
            with self.assertRaisesRegex(TimeoutError, "client startup logs"):
                ATrustLogin.wait_for_port(54631, timeout=1)

    def test_client_wait_rejects_nonpositive_timeout(self):
        with self.assertRaises(ValueError):
            ATrustLogin.wait_for_port(54631, timeout=0)

    def test_container_options_preserve_quoted_values(self):
        command = build_command('--portal_address="https://vpn.example.test" --password="test value *"')
        self.assertIn("--password=test value *", command)
        self.assertIn("--container_mode=True", command)

    def test_container_options_do_not_execute_shell_substitutions(self):
        command = build_command('--password="$(touch /tmp/unwanted-file)"')
        self.assertIn("--password=$(touch /tmp/unwanted-file)", command)

    def test_container_options_reject_unbalanced_quotes(self):
        with self.assertRaises(ValueError):
            build_command('--password="unfinished')

    def test_optional_cookies_are_not_added(self):
        for value in (None, ""):
            login = login_stub()
            login.cookie_tid = login.cookie_sig = value
            login.set_cli_cookie(force=True)
            login.driver.add_cookie.assert_not_called()

    def test_explicit_cookies_are_added_on_portal_only(self):
        login = login_stub()
        login.cookie_tid, login.cookie_sig = "test-tid", "test-signature"
        login.set_cli_cookie(force=True)
        self.assertEqual(login.driver.add_cookie.call_count, 2)
        login.driver.reset_mock()
        login.driver.current_url = "https://sso.example.test/login"
        login.set_cli_cookie(force=True)
        login.driver.add_cookie.assert_not_called()

    def test_redirected_portal_does_not_set_foreign_cookies(self):
        login = login_stub()
        login.driver.current_url = "https://sso.example.test/login"
        login.open_portal()
        login.driver.add_cookie.assert_not_called()
        login.driver.delete_cookie.assert_not_called()

    def test_authenticated_url_requires_portal_origin_and_route(self):
        login = login_stub()
        for address, expected in (
            ("https://vpn.example.test/#/app_center", True),
            ("https://vpn.example.test:443/#/user_info/profile", True),
            ("https://sso.example.test/#/app_center", False),
            ("https://vpn.example.test/#/login?redirect=app_center", False),
            ("http://vpn.example.test/#/app_center", False),
            ("about:blank", False),
        ):
            with self.subTest(address=address):
                login.driver.current_url = address
                self.assertEqual(login.is_logged(), expected)

    def test_corrupt_session_data_allows_browser_login(self):
        login = login_stub()
        with tempfile.TemporaryDirectory() as directory:
            login.data_dir = directory
            Path(directory, "ATrustLoginStorage.pkl").write_bytes(b"incomplete pickle")
            login.load_storage()
            login.driver.add_cookie.assert_not_called()

    def test_local_storage_values_use_script_arguments(self):
        login = login_stub()
        with tempfile.TemporaryDirectory() as directory:
            login.data_dir = directory
            data = ATrustLoginStorage(cookies=[], local_storage={"key'": "value'\\\n"})
            Path(directory, "ATrustLoginStorage.pkl").write_bytes(pickle.dumps(data))
            login.load_storage()
            login.driver.execute_script.assert_called_once_with(
                "window.localStorage.setItem(arguments[0], arguments[1]);", "key'", "value'\\\n"
            )

    def test_session_write_is_atomic(self):
        login = login_stub()
        login.driver.get_cookies.return_value = []
        login.driver.execute_script.return_value = {}
        with tempfile.TemporaryDirectory() as directory:
            login.data_dir = directory
            path = Path(directory, "ATrustLoginStorage.pkl")
            path.write_bytes(b"existing session")
            with patch("main.pickle.dump", side_effect=OSError("test write failure")):
                with self.assertRaises(OSError):
                    login.update_storage()
            self.assertEqual(path.read_bytes(), b"existing session")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_captcha_retry_returns_success(self):
        login = login_stub()
        for method in ("init", "wait_login_page", "delay_input", "delay_loading", "click_login_button", "set_cli_cookie"):
            setattr(login, method, MagicMock())
        login.is_logged = MagicMock(side_effect=[False, True])
        login.enter_credentials = MagicMock(return_value=True)
        login.driver.page_source = "图形校验码"
        self.assertTrue(login.login("test-user", "test-password"))
        login.driver.refresh.assert_called_once()


class SSOHandler(BaseHTTPRequestHandler):
    return_to_portal = True
    visits = []

    def do_GET(self):
        self.visits.append(self.path)
        port = self.server.server_port
        if self.path == "/login":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{port}/sso")
            self.end_headers()
            return
        html = "<!doctype html><meta charset='utf-8'><title>Test identity provider</title><p>Scan QR code</p>"
        if self.path == "/sso" and self.return_to_portal:
            html += f"<script>setTimeout(() => location.href='http://127.0.0.1:{port}/#/app_center', 800);</script>"
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(os.environ.get("ATRUST_BROWSER_TESTS") == "1", "Enable browser integration tests")
class SSOBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SSOHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        options = Options()
        for argument in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage"):
            options.add_argument(argument)
        if os.environ.get("CHROME_BINARY"):
            options.binary_location = os.environ["CHROME_BINARY"]
        cls.driver = webdriver.Chrome(service=Service(os.environ.get("CHROMEDRIVER")), options=options)
        cls.addClassCleanup(cls.driver.quit)

    def setUp(self):
        SSOHandler.return_to_portal = True
        SSOHandler.visits = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.login = login_stub()
        self.login.driver = self.driver
        self.login.portal_address = self.origin + "/login"
        self.login.portal_host = "127.0.0.1"
        self.login.data_dir = self.directory.name
        self.login.initialized = False
        self.login.interactive = False
        self.login.login_timeout = 3
        self.login.wait = WebDriverWait(self.driver, 2)
        self.login.delay_loading = lambda: None
        self.login.delay_input = lambda: None

    def test_sso_redirect_completes_without_credentials_or_terminal(self):
        with patch("builtins.input", side_effect=AssertionError("Terminal input is not available")):
            self.assertTrue(self.login.login())
        self.assertTrue(self.login.is_logged())
        self.assertTrue(Path(self.directory.name, "ATrustLoginStorage.pkl").is_file())
        self.assertEqual(SSOHandler.visits.count("/sso"), 1)
        self.assertEqual(SSOHandler.visits.count("/login"), 1)

    def test_manual_wait_timeout_preserves_sso_page(self):
        SSOHandler.return_to_portal = False
        self.login.login_timeout = 0.1
        with self.assertRaises(TimeoutException):
            self.login.login()
        self.assertIn("localhost", self.driver.current_url)
        self.assertTrue(self.driver.current_url.endswith("/sso"))
        self.assertEqual(SSOHandler.visits.count("/sso"), 1)

    def test_authenticated_page_initializes_without_password_form(self):
        self.login.portal_address = self.origin + "/#/app_center"
        self.assertTrue(self.login.login())
        self.assertTrue(self.login.initialized)

    def test_interactive_verification_waits_without_stdin(self):
        self.login.interactive = True
        self.login.open_portal()
        with patch("builtins.input", side_effect=AssertionError("No stdin")):
            self.login.require_interact()
        self.assertTrue(self.login.is_logged())


if __name__ == "__main__":
    unittest.main()