import json
import os.path
import pickle
import platform
import socket
import subprocess
import time
import urllib.request
from typing import Dict, List, Any
from urllib.parse import urlparse

import pyotp
from loguru import logger
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class ATrustLoginStorage(BaseModel):
    cookies: List[Dict[str, Any]]
    local_storage: Dict[str, Any]

class ATrustLogin:
    def __init__(self, portal_address, driver_path=None, browser_path=None, driver_type=None, data_dir="data", cookie_tid=None, cookie_sig=None, interactive=False, container_mode=False):
        self.initialized = False
        self.container_mode = container_mode
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.interactive = interactive
        self.portal_address = portal_address
        self.portal_host = urlparse(portal_address).hostname
        self.cookie_tid = cookie_tid
        self.cookie_sig = cookie_sig

        self.must_be_logged_keywords = ['app_center', 'user_info', 'app_apply', 'device_manage']
        # self.must_not_logged_keywords = ['login', 'totpAuth', 'captcha', 'page_auth_trust_terminal', 'smsAuth']

        if self.container_mode:
            from selenium.webdriver.chrome.options import Options

            DEBUG_PORT = "55555"
            PROFILE_DIR = "Default"

            binary_location = browser_path or "/usr/bin/chromium"
            chrome_data_dir = os.path.join("/tmp", "chrome-data")
            log_file = os.path.join(chrome_data_dir, "chrome.log")
            os.makedirs(chrome_data_dir, exist_ok=True)

            logger.info(f"Starting Chrome with debug port {DEBUG_PORT}")
            self.chrome_process = subprocess.Popen([
                    binary_location,
                    f"--remote-debugging-port={DEBUG_PORT}",
                    f"--user-data-dir={chrome_data_dir}",
                    f"--profile-directory={PROFILE_DIR}",
                    "--ignore-certificate-errors",
                    "--ignore-ssl-errors", 
                    "--no-sandbox", 
                    "--lang=zh-CN", 
                    "--disable-gpu", 
                    "--disable-extensions",
                    "--disable-web-security",
                    "--allow-insecure-localhost",
                    "--window-size=896,672",
                    "data:,"
                ], stdout=open(log_file, "w"), stderr=subprocess.STDOUT
            )

            logger.info(f"Chrome started, PID {self.chrome_process.pid}, waiting for DevTools ...")
            while True:
                if self.chrome_process.poll() is not None:
                    raise RuntimeError(f"Chrome exited with code {self.chrome_process.returncode}")
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
                    logger.info("DevTools ready.")
                    break
                except:
                    time.sleep(3)

            self.options = Options()
            self.options.debugger_address = f"127.0.0.1:{DEBUG_PORT}"
            self.driver = webdriver.Chrome(options=self.options)

        else:
            if driver_type is None:
                system = platform.system()
                if system == "Windows":
                    driver_type = "edge"
                else:
                    driver_type = "chrome"

            logger.debug(f"Driver: {driver_type}: {driver_path}")

            if driver_type == "edge":
                from selenium.webdriver.edge.options import Options
                from selenium.webdriver.edge.service import Service
                driver_cls = webdriver.Edge
            else:
                from selenium.webdriver.chrome.options import Options
                from selenium.webdriver.chrome.service import Service
                driver_cls = webdriver.Chrome

            self.options = Options()
            self.options.add_argument('--profile-directory=ATrustLogin')
            self.options.add_argument("--ignore-certificate-errors")
            self.options.add_argument("--ignore-ssl-errors")
            self.options.add_argument("--no-sandbox")
            self.options.add_argument("--lang=zh-CN")
            self.options.add_argument("--disable-gpu")
            self.options.add_argument("--disable-extensions")
            self.options.add_argument("--disable-web-security")
            self.options.add_argument("--allow-insecure-localhost")
            self.options.add_argument("--window-size=896,672")
            self.options.add_experimental_option("prefs", {"intl.accept_languages": "zh-CN"})
            if browser_path is not None:
                self.options.binary_location = browser_path
            self.driver = driver_cls(service=Service(driver_path), options=self.options)

        self.wait = WebDriverWait(self.driver, 10)
        logger.debug("Selenium init successfully.")

    # 打开默认的portal地址并等待sangfor_main_auth_container出现
    def open_portal(self):
        self.driver.get(self.portal_address)

        if self.driver.get_cookie("language"):
            self.driver.delete_cookie("language")
        if self.driver.get_cookie("lang"):
            self.driver.delete_cookie("lang")

        self.driver.add_cookie(
            {
                "name": "language",
                "value": "zh-CN",
                "domain": self.portal_host,
                "path": "/",
            }
        )

        self.driver.add_cookie(
            {
                "name": "lang",
                "value": "zh-cn",
                "domain": self.portal_host,
                "path": "/",
            }
        )

    def wait_login_page(self):
        # 使用显式等待sangfor_main_auth_container元素出现
        self.wait.until(EC.presence_of_element_located((By.ID, "sangfor_main_auth_container")))
        self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "login-panel")))
        self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    @staticmethod
    def delay_input():
        time.sleep(0.5)

    @staticmethod
    def delay_loading():
        time.sleep(5)

    # 递归查找具有指定placeholder的前两个非hidden类型的input框
    def find_input_fields(self, element, inputs_found=None):
        if inputs_found is None:
            inputs_found = []

        # 检查当前节点是否是符合条件的input框
        if element.tag_name == "input":
            placeholder = element.get_attribute("placeholder")
            input_type = element.get_attribute("type")
            # 确保input具有指定的placeholder，并且不是hidden类型
            if placeholder and ("账号" in placeholder or "account" in placeholder.lower() or "密码" in placeholder or "password" in placeholder.lower()) and input_type != "hidden":
                inputs_found.append(element)
                # 如果找到两个符合条件的input框就返回
                if len(inputs_found) == 2:
                    return inputs_found

        # 递归遍历所有子节点
        child_elements = element.find_elements(By.XPATH, "./*")
        for child in child_elements:
            result = self.find_input_fields(child, inputs_found)
            if result and len(result) == 2:
                return result
        return inputs_found

    # 输入用户名和密码
    def enter_credentials(self, username, password):
        try:
            element = self.driver.find_element(By.XPATH, "//div[contains(@class, 'server-name') and contains(text(), '本地密码')]")
            if element.is_displayed():
                self.delay_input()
                self.scroll_and_click(element)
        except:
            pass

        # 找到包含ID=sangfor_main_auth_container的div
        main_auth_div = self.driver.find_element(By.ID, "sangfor_main_auth_container")

        # 递归查找前两个input框
        input_fields = self.find_input_fields(main_auth_div)

        if len(input_fields) >= 2:
            username_input = input_fields[0]
            password_input = input_fields[1]

            # 输入用户名和密码
            self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(username_input)))
            self.delay_input()
            username_input.clear()
            username_input.send_keys(username)

            self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(password_input)))
            self.delay_input()
            password_input.clear()
            password_input.send_keys(password)

            checkbox = main_auth_div.find_element(By.XPATH, "//input[@type='checkbox']")
            # 检查checkbox是否已经被选中
            if not checkbox.is_selected():
                self.delay_input()
                self.scroll_and_click(checkbox)  # 如果没有选中，就点击选中

            logger.debug("Filled username and password")
        else:
            logger.info("未找到用户名或密码输入框")

    # 查找并点击登录按钮
    def click_login_button(self):
        # 在div class=login-panel中寻找包含“登录”或“login”或“log in”的按钮
        login_panel = self.driver.find_element(By.CLASS_NAME, "login-panel")
        buttons = login_panel.find_elements(By.TAG_NAME, "button")

        for button in buttons:
            button_text = button.text.lower()
            if "登录" in button_text or "login" in button_text or "log in" in button_text:
                self.scroll_and_click(button)
                return
        logger.info("未找到符合条件的登录按钮")

    def load_storage(self):
        # 从pickle文件中加载存储的数据
        try:
            if os.path.exists(os.path.join(self.data_dir, "ATrustLoginStorage.pkl")):
                with open(os.path.join(self.data_dir, "ATrustLoginStorage.pkl"), "rb") as f:
                    data = pickle.load(f)
                    # 从cookies中加载cookie
                    for cookie in data.cookies:
                        self.driver.delete_cookie(cookie['name'])
                        self.driver.add_cookie(cookie)
                    # 从local_storage中加载local storage
                    for key, value in data.local_storage.items():
                        self.driver.execute_script(f"window.localStorage.setItem('{key}', '{value}')")
                    logger.info("Loaded storage data")
        except FileNotFoundError:
            logger.info("未找到存储的数据")

        self.set_cli_cookie(force=False)

    def scroll_to(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView();", element)

    def scroll_and_click(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView();", element)
        element.click()
        return element

    def set_cli_cookie(self, force=False):
        if force or not self.driver.get_cookie("tid"):
            self.driver.delete_cookie("tid")
            self.driver.add_cookie({
                "name": "tid",
                "value": self.cookie_tid,
                "domain": self.portal_host,
                "path": "/"
            })

        if force or not self.driver.get_cookie("tid.sig"):
            self.driver.delete_cookie("tid.sig")
            self.driver.add_cookie({
                "name": "tid.sig",
                "value": self.cookie_sig,
                "domain": self.portal_host,
                "path": "/"
            })

    def require_interact(self):
        if self.interactive:
            input("Press any key to continue")
        else:
            raise Exception("User Interact required")

    def init(self):
        if not self.initialized:
            self.open_portal()
            self.wait_login_page()
            self.delay_loading()
            self.load_storage()
            self.initialized = True

    def login(self, username, password, totp_key, **kwargs):
        self.init()

        if self.is_logged():
            logger.info("Already logged in")
            return True

        self.enter_credentials(username=username, password=password)
        self.delay_input()
        self.click_login_button()

        logger.info("Performed basic login action")

        self.delay_loading()
        logger.debug("Checking captcha ...")

        if "图形校验码" in self.driver.page_source:
            if 'is_retried' not in kwargs:
                self.set_cli_cookie(force=True)
                self.driver.refresh()
                self.login( username, password, totp_key, is_retried=True)
                return
            else:
                logger.warning("Need to handle captcha, press any key to continue")
                self.require_interact()

        if "TOTP" in self.driver.page_source and "二次认证" in self.driver.page_source:
            if totp_key is not None:
                totp = pyotp.TOTP(totp_key)
                totp_code = totp.now()

                logger.info(f"TOTP code: {totp_code}")
                totp_input = self.driver.find_element(By.XPATH, "//input[contains(@class, 'totp')]")

                self.scroll_and_click(self.wait.until(EC.element_to_be_clickable(totp_input)))
                self.delay_input()
                totp_input.send_keys(totp_code)

                submit_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
                self.wait.until(EC.element_to_be_clickable(submit_button))
                self.delay_input()
                self.scroll_and_click(submit_button)
                logger.info(f"Performed TOTP login action with code: {totp_code}")
                self.delay_loading()
            else:
                logger.info("Need to handle TOTP, press any key to continue")
                self.require_interact()

        logger.info("Performed verification code login action")

        if self.is_logged():
            logger.info("Login Success")
            self.update_storage()
            return True

    def is_logged(self):
        """
        检查是否已经登录
        :return: None if not sure, True if logged, False if not logged
        """

        if self.driver.current_url.startswith('about:'):
            return None

        url = urlparse(self.driver.current_url)
        return any(keyword in url.fragment for keyword in self.must_be_logged_keywords)

    def close(self):
        self.driver.quit()
        if self.container_mode and hasattr(self, 'chrome_process') and self.chrome_process.poll() is None:
            self.chrome_process.terminate()
            try:
                self.chrome_process.wait(timeout=5)
            except:
                self.chrome_process.kill()
                self.chrome_process.wait()

    def __enter__(self):
        return self

    def update_storage(self):
        data = ATrustLoginStorage(
            cookies=self.driver.get_cookies(),
            local_storage=self.driver.execute_script("return window.localStorage")
        )

        # save with pickle
        with open(os.path.join(self.data_dir, "ATrustLoginStorage.pkl"), "wb") as f:
            pickle.dump(data, f)

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def wait_for_port(port, host='localhost'):
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                try:
                    s.connect((host, port))
                    logger.info(f"Detected aTrust is listening on port {port}")
                    s.close()
                    break
                except (socket.timeout, ConnectionRefusedError):
                    logger.info(f"aTrust Port {port} is not yet being listened on. Waiting for aTrust start ...")
                    ATrustLogin.delay_loading()

def main(portal_address, username, password, totp_key=None, cookie_tid=None, cookie_sig=None, keepalive=200, data_dir="./data", driver_type=None, driver_path=None, browser_path=None, interactive=False, wait_atrust=True, container_mode=False):
    logger.info("Opening Web Browser")

    if wait_atrust:
        ATrustLogin.wait_for_port(54631)

    # 创建ATrustLogin对象
    at = ATrustLogin(data_dir=data_dir, portal_address=portal_address, cookie_tid=cookie_tid, cookie_sig=cookie_sig, driver_type=driver_type, driver_path=driver_path, browser_path=browser_path, interactive=interactive, container_mode=container_mode)

    at.init()

    while True:
        try:
            if not at.is_logged():
                logger.info("Session lost. Trying to login again ...")
                at.open_portal()
                at.delay_loading()
                if at.login(username=username, password=password, totp_key=totp_key) is True:
                    at.delay_loading()
                    at.delay_loading()

            if keepalive <= 0:
                at.close()
                exit(0)
            else:
                time.sleep(keepalive)
                at.open_portal()
                at.delay_loading()
        except Exception as e:
            logger.error("An error occurred when trying to login, retrying ...")
            logger.exception(e)
            at.delay_loading()

if __name__ == "__main__":
    from fire import Fire
    Fire(main)
