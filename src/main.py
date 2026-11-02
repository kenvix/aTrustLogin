import os.path
import pickle
import platform
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from typing import Dict, List, Any
from urllib.parse import urlparse

import pyotp
from loguru import logger
from pydantic import BaseModel
from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException, NoSuchWindowException, TimeoutException, WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from browser_log import BrowserLog


class ATrustLoginStorage(BaseModel):
    cookies: List[Dict[str, Any]]
    local_storage: Dict[str, Any]


class ATrustLogin:
    def __init__(self, portal_address, driver_path=None, browser_path=None, driver_type=None, data_dir="data", cookie_tid=None, cookie_sig=None, interactive=False, container_mode=False, login_timeout=300):
        self.initialized = False
        self.container_mode = container_mode
        self.driver = None
        self.chrome_process = None
        self._browser_log = None
        self._profile = None
        self.portal_address = portal_address
        self.portal_host = urlparse(portal_address).hostname
        self.portal_origin(portal_address)
        if login_timeout <= 0:
            raise ValueError("login_timeout must be greater than zero")
        self.login_timeout = login_timeout
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.interactive = interactive
        self.cookie_tid = cookie_tid
        self.cookie_sig = cookie_sig
        self.must_be_logged_keywords = ['app_center', 'user_info', 'app_apply', 'device_manage']

        try:
            self._start_browser(driver_path, browser_path, driver_type)
            self.configure_client_access()
            self.wait = WebDriverWait(self.driver, 10)
        except BaseException:
            self.close()
            raise
        logger.debug("Selenium init successfully.")

    @staticmethod
    def portal_origin(address):
        portal = urlparse(address)
        if portal.scheme not in ("http", "https") or not portal.hostname:
            raise ValueError("portal_address must be an HTTP or HTTPS URL")
        port = portal.port or (443 if portal.scheme == "https" else 80)
        return portal.scheme, portal.hostname, port

    def is_portal_page(self):
        try:
            return self.portal_origin(self.driver.current_url) == self.portal_origin(self.portal_address)
        except ValueError:
            return False

    def _start_browser(self, driver_path, browser_path, driver_type):
        self._profile = tempfile.TemporaryDirectory(prefix="atrust-chrome-")
        arguments = [
            f"--user-data-dir={self._profile.name}",
            "--ignore-certificate-errors", "--ignore-ssl-errors", "--no-sandbox",
            "--lang=zh-CN", "--disable-gpu", "--disable-extensions",
            "--disable-web-security", "--allow-insecure-localhost",
            "--window-size=896,672", "--disk-cache-size=67108864",
            "--media-cache-size=33554432",
        ]
        if self.container_mode:
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            debug_port = 55555
            binary_location = browser_path or "/usr/bin/chromium"
            logger.info("Starting Chrome with debug port {}", debug_port)
            self.chrome_process = subprocess.Popen(
                [binary_location, f"--remote-debugging-port={debug_port}",
                 "--profile-directory=Default", *arguments, "data:,"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self._browser_log = BrowserLog(
                self.chrome_process.stdout, os.path.join(self.data_dir, "chrome.log")
            )
            deadline = time.monotonic() + 60
            while True:
                if self.chrome_process.poll() is not None:
                    raise RuntimeError(f"Chrome exited with code {self.chrome_process.returncode}")
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{debug_port}/json/version", timeout=2
                    ):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Chrome DevTools did not become ready within 60 seconds")
                    time.sleep(1)
            self.options = Options()
            self.options.debugger_address = f"127.0.0.1:{debug_port}"
            self.driver = webdriver.Chrome(service=Service(driver_path), options=self.options)
        else:
            if driver_type is None:
                driver_type = "edge" if platform.system() == "Windows" else "chrome"
            logger.debug("Driver: {}: {}", driver_type, driver_path)
            if driver_type == "edge":
                from selenium.webdriver.edge.options import Options
                from selenium.webdriver.edge.service import Service
                driver_cls = webdriver.Edge
            else:
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.chrome.service import Service
                driver_cls = webdriver.Chrome
            self.options = Options()
            for argument in arguments:
                self.options.add_argument(argument)
            self.options.add_argument("--profile-directory=ATrustLogin")
            self.options.add_experimental_option("prefs", {"intl.accept_languages": "zh-CN"})
            if browser_path is not None:
                self.options.binary_location = browser_path
            self.driver = driver_cls(service=Service(driver_path), options=self.options)

    def configure_client_access(self):
        """Allow the configured portal to contact the local aTrust client."""
        portal = urlparse(self.portal_address)
        self.portal_origin(self.portal_address)
        host = portal.hostname
        if ":" in host:
            host = f"[{host}]"
        origin = f"{portal.scheme}://{host}"
        if portal.port is not None:
            origin += f":{portal.port}"
        for permission in ("loopback-network", "local-network-access"):
            try:
                self.driver.execute_cdp_cmd("Browser.setPermission", {
                    "permission": {"name": permission},
                    "setting": "granted", "origin": origin,
                })
                logger.debug("Granted {} permission for {}", permission, origin)
                return True
            except WebDriverException:
                logger.debug("Could not set {} permission", permission)
        logger.warning(
            "Could not configure browser access to the local aTrust client. "
            "Allow local network access for the portal in the browser site settings."
        )
        return False

    def open_portal(self):
        self.driver.get(self.portal_address)
        if not self.is_portal_page():
            return
        for name, value in (("language", "zh-CN"), ("lang", "zh-cn")):
            self.driver.delete_cookie(name)
            self.driver.add_cookie({"name": name, "value": value, "path": "/"})

    def wait_login_page(self):
        self.wait.until(lambda d: self.is_portal_page())
        self.wait.until(EC.presence_of_element_located((By.ID, "sangfor_main_auth_container")))
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "login-panel")))
        self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    @staticmethod
    def delay_input():
        time.sleep(0.5)

    @staticmethod
    def delay_loading():
        time.sleep(5)

    def find_input_fields(self, element, inputs_found=None):
        if inputs_found is None:
            inputs_found = []
        if element.tag_name == "input":
            placeholder = element.get_attribute("placeholder")
            input_type = element.get_attribute("type")
            if placeholder and ("账号" in placeholder or "account" in placeholder.lower() or "密码" in placeholder or "password" in placeholder.lower()) and input_type != "hidden" and element.is_displayed() and element.is_enabled():
                inputs_found.append(element)
                if len(inputs_found) == 2:
                    return inputs_found
        for child in element.find_elements(By.XPATH, "./*"):
            result = self.find_input_fields(child, inputs_found)
            if result and len(result) == 2:
                return result
        return inputs_found

    def enter_credentials(self, username, password):
        if not self.is_portal_page():
            return False
        try:
            element = self.driver.find_element(By.XPATH, "//div[contains(@class, 'server-name') and contains(text(), '本地密码')]")
            if element.is_displayed():
                self.delay_input()
                self.scroll_and_click(element)
        except WebDriverException:
            pass
        main_auth_div = self.driver.find_element(By.ID, "sangfor_main_auth_container")
        input_fields = self.find_input_fields(main_auth_div)
        if len(input_fields) < 2:
            return False
        for field, value in zip(input_fields, (username, password)):
            self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(field)))
            self.delay_input()
            field.clear()
            field.send_keys(value)
        self.select_login_checkbox(main_auth_div)
        logger.debug("Filled username and password")
        return True

    def select_login_checkbox(self, main_auth_div):
        """Select the first available login checkbox through its visible control."""
        checkboxes = main_auth_div.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for checkbox in checkboxes:
            if not checkbox.is_enabled():
                continue
            labels = self.driver.execute_script(
                "return Array.from(arguments[0].labels || []);", checkbox
            )
            targets = labels + [checkbox]
            target = next((item for item in targets if item.is_displayed()), None)
            if target is None:
                continue
            if not checkbox.is_selected():
                self.delay_input()
                self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(target)))
                self.wait.until(EC.element_to_be_selected(checkbox))
            return

    def click_login_button(self):
        login_panel = self.driver.find_element(By.CLASS_NAME, "login-panel")
        for button in login_panel.find_elements(By.TAG_NAME, "button"):
            button_text = button.text.lower()
            if "登录" in button_text or "login" in button_text or "log in" in button_text:
                self.scroll_and_click(button)
                return
        raise RuntimeError("No login button found in the portal login panel")

    def load_storage(self):
        if not self.is_portal_page():
            return False
        restored = False
        try:
            with open(os.path.join(self.data_dir, "ATrustLoginStorage.pkl"), "rb") as f:
                data = pickle.load(f)
            for cookie in data.cookies:
                if cookie.get("expiry", float("inf")) <= time.time():
                    continue
                try:
                    self.driver.delete_cookie(cookie['name'])
                    self.driver.add_cookie(cookie)
                    restored = True
                except WebDriverException:
                    logger.warning("A stored cookie could not be restored")
            for key, value in data.local_storage.items():
                self.driver.execute_script("window.localStorage.setItem(arguments[0], arguments[1]);", key, value)
                restored = True
            logger.info("Loaded storage data")
        except FileNotFoundError:
            pass
        except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError, TypeError):
            logger.warning("Stored session data could not be read; continuing with browser login")
        self.set_cli_cookie(force=False)
        return restored or bool(self.cookie_tid or self.cookie_sig)

    def scroll_to(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView();", element)

    def scroll_and_click(self, element):
        self.scroll_to(element)
        element.click()
        return element

    def set_cli_cookie(self, force=False):
        if not self.is_portal_page():
            return
        for name, value in (("tid", self.cookie_tid), ("tid.sig", self.cookie_sig)):
            if value and (force or not self.driver.get_cookie(name)):
                self.driver.delete_cookie(name)
                self.driver.add_cookie({
                    "name": name, "value": value, "domain": self.portal_host, "path": "/",
                })

    def wait_for_manual_login(self):
        logger.info("Complete login in the browser or VNC; waiting up to {} seconds", self.login_timeout)
        WebDriverWait(self.driver, self.login_timeout).until(lambda d: self.is_logged())
        self.update_storage()
        return True

    def require_interact(self, condition=None):
        if not self.interactive:
            raise RuntimeError("Browser interaction required; use --interactive=True")
        logger.info("Complete verification in the browser or VNC")
        WebDriverWait(self.driver, self.login_timeout).until(condition or (lambda d: self.is_logged()))

    def init(self):
        if not self.initialized:
            self.open_portal()
            self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            self.delay_loading()
            if self.load_storage():
                self.driver.refresh()
            self.initialized = True

    def login(self, username=None, password=None, totp_key=None, **kwargs):
        if (username is None) != (password is None):
            raise ValueError("Provide both username and password, or omit both for browser login")
        self.init()
        if self.is_logged():
            logger.info("Already logged in")
            return True
        if username is None:
            return self.wait_for_manual_login()
        try:
            self.wait_login_page()
        except TimeoutException:
            if self.interactive:
                return self.wait_for_manual_login()
            raise
        if not self.enter_credentials(username=username, password=password):
            if self.interactive:
                return self.wait_for_manual_login()
            raise RuntimeError("No password login form found; omit credentials for SSO login")
        self.delay_input()
        self.click_login_button()
        logger.info("Performed basic login action")
        self.delay_loading()
        if "图形校验码" in self.driver.page_source:
            if 'is_retried' not in kwargs:
                self.set_cli_cookie(force=True)
                self.driver.refresh()
                return self.login(username, password, totp_key, is_retried=True)
            self.require_interact(lambda d: self.is_logged() or "图形校验码" not in d.page_source)
        if "TOTP" in self.driver.page_source and "二次认证" in self.driver.page_source:
            if totp_key:
                totp_code = pyotp.TOTP(totp_key).now()
                totp_input = self.driver.find_element(By.XPATH, "//input[contains(@class, 'totp')]")
                self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(totp_input)))
                self.delay_input()
                totp_input.clear()
                totp_input.send_keys(totp_code)
                submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
                self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(submit_button)))
                logger.info("Submitted TOTP verification")
                self.delay_loading()
            else:
                self.require_interact()
        if self.is_logged():
            logger.info("Login Success")
            self.update_storage()
            return True
        if self.interactive:
            return self.wait_for_manual_login()
        return False

    def is_logged(self):
        if not self.is_portal_page():
            return False
        segments = urlparse(self.driver.current_url).fragment.split("?", 1)[0].strip("/").split("/")
        return any(segment in self.must_be_logged_keywords for segment in segments)

    def close(self):
        try:
            driver = getattr(self, "driver", None)
            self.driver = None
            if driver is not None:
                try:
                    driver.quit()
                except WebDriverException:
                    logger.warning("WebDriver could not close normally")
        finally:
            try:
                process = getattr(self, "chrome_process", None)
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            finally:
                self.chrome_process = None
                browser_log = getattr(self, "_browser_log", None)
                if browser_log is not None:
                    browser_log.close()
                    self._browser_log = None
                profile = getattr(self, "_profile", None)
                if profile is not None:
                    profile.cleanup()
                    self._profile = None

    def __enter__(self):
        return self

    def update_storage(self):
        if not self.is_portal_page():
            return
        data = ATrustLoginStorage(
            cookies=self.driver.get_cookies(),
            local_storage=self.driver.execute_script("return window.localStorage")
        )
        path = os.path.join(self.data_dir, "ATrustLoginStorage.pkl")
        fd, temporary = tempfile.mkstemp(dir=self.data_dir, prefix=".atrust-storage-")
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(data, f)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def wait_for_port(port, host='localhost', timeout=120):
        if timeout <= 0:
            raise ValueError("client_timeout must be greater than zero")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"aTrust did not listen on {host}:{port} within {timeout} seconds. "
                    "Check the aTrust client process, client version, and client startup logs."
                )
            try:
                with socket.create_connection((host, port), timeout=min(1, remaining)):
                    logger.info("Detected aTrust is listening on port {}", port)
                    return
            except OSError:
                logger.info("Waiting for aTrust on {}:{}", host, port)
                time.sleep(min(5, max(0, deadline - time.monotonic())))


def main(portal_address, username=None, password=None, totp_key=None, cookie_tid=None, cookie_sig=None, keepalive=200, data_dir="./data", driver_type=None, driver_path=None, browser_path=None, interactive=False, wait_atrust=True, container_mode=False, login_timeout=300, client_timeout=120):
    if (username is None) != (password is None):
        raise ValueError("Provide both username and password, or omit both for browser login")
    if login_timeout <= 0 or client_timeout <= 0:
        raise ValueError("login_timeout and client_timeout must be greater than zero")
    ATrustLogin.portal_origin(portal_address)
    if wait_atrust:
        ATrustLogin.wait_for_port(54631, timeout=client_timeout)
    at = ATrustLogin(
        data_dir=data_dir, portal_address=portal_address, cookie_tid=cookie_tid,
        cookie_sig=cookie_sig, driver_type=driver_type, driver_path=driver_path,
        browser_path=browser_path, interactive=interactive,
        container_mode=container_mode, login_timeout=login_timeout,
    )
    try:
        while True:
            try:
                if not at.initialized or not at.is_logged():
                    if at.initialized:
                        at.open_portal()
                        at.delay_loading()
                    success = at.login(username=username, password=password, totp_key=totp_key)
                else:
                    success = True
                if keepalive <= 0:
                    if not success:
                        raise RuntimeError("Login did not complete")
                    return
                time.sleep(keepalive)
                at.open_portal()
                at.delay_loading()
            except (InvalidSessionIdException, NoSuchWindowException):
                raise
            except Exception as exc:
                if keepalive <= 0:
                    raise
                logger.error("Login attempt failed ({}); retrying after 5 seconds", type(exc).__name__)
                at.delay_loading()
    finally:
        at.close()


if __name__ == "__main__":
    from fire import Fire

    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        Fire(main)
    except Exception as exc:
        logger.error("Autologin stopped: {}: {}", type(exc).__name__, str(exc))
        raise SystemExit(1)
