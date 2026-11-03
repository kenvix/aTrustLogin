import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fire import Fire
from selenium import webdriver

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from launcher import build_command
from main import ATrustLogin, main


class BrowserResourceTests(unittest.TestCase):
    def test_cli_defaults_are_forwarded(self):
        with patch("main.ATrustLogin") as login:
            main("https://vpn.example.test", wait_atrust=False, keepalive=0)
            settings = login.call_args.kwargs
            self.assertEqual(settings["disk_cache_size_mib"], 256)
            self.assertEqual(settings["browser_log_size_mib"], 20)
            self.assertEqual(settings["browser_log_files"], 5)
            login.return_value.close.assert_called_once()

    def test_cli_custom_settings_are_forwarded(self):
        with patch("main.ATrustLogin") as login:
            Fire(main, command=[
                "--portal_address=https://vpn.example.test", "--wait_atrust=False",
                "--keepalive=0", "--disk_cache_size_mib=512",
                "--browser_log_size_mib=50", "--browser_log_files=7",
            ])
            settings = login.call_args.kwargs
            self.assertEqual(settings["disk_cache_size_mib"], 512)
            self.assertEqual(settings["browser_log_size_mib"], 50)
            self.assertEqual(settings["browser_log_files"], 7)

    def test_container_options_reach_cli(self):
        command = build_command(
            '--portal_address="https://vpn.example.test" --keepalive=0 '
            '--disk_cache_size_mib=512 --browser_log_size_mib=50 --browser_log_files=7'
        )
        with patch("main.ATrustLogin") as login:
            Fire(main, command=command[2:])
            settings = login.call_args.kwargs
            self.assertTrue(settings["container_mode"])
            self.assertEqual(settings["disk_cache_size_mib"], 512)
            self.assertEqual(settings["browser_log_size_mib"], 50)
            self.assertEqual(settings["browser_log_files"], 7)

    def test_custom_cache_applies_to_native_browsers(self):
        for driver_type in ("chrome", "edge"):
            with self.subTest(driver_type=driver_type), tempfile.TemporaryDirectory() as directory, \
                    patch("main.webdriver.Chrome") as chrome, patch("main.webdriver.Edge") as edge:
                with ATrustLogin("https://vpn.example.test", data_dir=directory,
                                 driver_type=driver_type, disk_cache_size_mib=512):
                    driver = edge if driver_type == "edge" else chrome
                    arguments = driver.call_args.kwargs["options"].arguments
                    cache_arguments = [arg for arg in arguments if "cache-size=" in arg]
                    self.assertEqual(cache_arguments, ["--disk-cache-size=536870912"])

    def test_container_resource_settings(self):
        for settings, cache_bytes, log_bytes, backups in (
            ({}, 268435456, 20971520, 4),
            ({"disk_cache_size_mib": 512, "browser_log_size_mib": 50,
              "browser_log_files": 7}, 536870912, 52428800, 6),
        ):
            process = MagicMock()
            process.poll.return_value = None
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory, \
                    patch("main.subprocess.Popen", return_value=process) as popen, \
                    patch("main.BrowserLog") as log, patch("main.urllib.request.urlopen"), \
                    patch("main.webdriver.Chrome"):
                with ATrustLogin("https://vpn.example.test", data_dir=directory,
                                 container_mode=True, **settings):
                    arguments = popen.call_args.args[0]
                    cache_arguments = [arg for arg in arguments if "cache-size=" in arg]
                    self.assertEqual(cache_arguments, [f"--disk-cache-size={cache_bytes}"])
                    log.assert_called_once_with(
                        process.stdout, os.path.join(directory, "chrome.log"),
                        max_bytes=log_bytes, backup_count=backups,
                    )

    @staticmethod
    def invalid_settings():
        for name in ("disk_cache_size_mib", "browser_log_size_mib", "browser_log_files"):
            for value in (0, -1, True, False, 1.5, "20", None):
                yield name, value
        yield "browser_log_files", 1

    def test_invalid_settings_fail_before_client_wait(self):
        for name, value in self.invalid_settings():
            with self.subTest(name=name, value=value), patch("main.ATrustLogin") as login:
                with self.assertRaisesRegex(ValueError, name):
                    main("https://vpn.example.test", **{name: value})
                login.wait_for_port.assert_not_called()
                login.assert_not_called()

    def test_invalid_settings_fail_before_browser_start(self):
        for name, value in self.invalid_settings():
            with self.subTest(name=name, value=value), \
                    patch("main.ATrustLogin._start_browser") as start, \
                    patch("main.os.makedirs") as mkdir:
                with self.assertRaisesRegex(ValueError, name):
                    ATrustLogin("https://vpn.example.test", **{name: value})
                start.assert_not_called()
                mkdir.assert_not_called()

    def test_minimum_settings_are_supported(self):
        with patch("main.ATrustLogin") as login:
            main("https://vpn.example.test", wait_atrust=False, keepalive=0,
                 disk_cache_size_mib=1, browser_log_size_mib=1, browser_log_files=2)
            self.assertEqual(login.call_args.kwargs["browser_log_files"], 2)


@unittest.skipUnless(os.environ.get("ATRUST_BROWSER_TESTS") == "1",
                     "Enable browser integration tests")
class BrowserResourceIntegrationTests(unittest.TestCase):
    def test_browser_starts_with_configured_cache(self):
        chrome = webdriver.Chrome

        def start_headless(**kwargs):
            kwargs["options"].add_argument("--headless=new")
            kwargs["options"].add_argument("--disable-dev-shm-usage")
            return chrome(**kwargs)

        binary = os.environ.get("CHROME_BINARY") or shutil.which("google-chrome") or shutil.which("chromium")
        for settings, expected in (({}, 268435456), ({"disk_cache_size_mib": 512}, 536870912)):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory, \
                    patch("main.webdriver.Chrome", side_effect=start_headless):
                with ATrustLogin("https://vpn.example.test", data_dir=directory,
                                 driver_type="chrome", browser_path=binary,
                                 driver_path=os.environ.get("CHROMEDRIVER"), **settings) as login:
                    arguments = login.driver.execute_cdp_cmd("Browser.getBrowserCommandLine", {})["arguments"]
                    self.assertIn(f"--disk-cache-size={expected}", arguments)
                    login.driver.get("data:text/html,<title>Cache configuration</title>")
                    self.assertEqual(login.driver.title, "Cache configuration")


if __name__ == "__main__":
    unittest.main()
