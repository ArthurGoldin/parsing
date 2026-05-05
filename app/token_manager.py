from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import json
import os
import pickle
import logging
import logging.config
import time
import configparser
from proxy_manager import ProxyManager, ProxyUnavailableError
import re
import platform

current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

# Configure logging
try:
    from logging_setup import setup_logging
    logger = setup_logging('token_manager')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('token_manager')
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")


# Read configuration
config = configparser.ConfigParser()
config.read(config_path)

data_dir = os.path.join(current_dir, config.get('storage', 'data_directory'))
token_dir = config.get('storage', 'token_sub_dir')
proxy_dir = config.get('storage', 'proxy_dir')


class TokenManager:
    def __init__(
        self,
        proxy_manager: ProxyManager = None,
        url="https://uzum.uz/ru",
        proxy_scheme='http',
        max_retries=5,
        save_token=False,
        save_cookies=False,
        cookies_path="cookies/cookies.pkl",
        save_screenshot=False
    ):
        self.url = url
        self.max_retries = max_retries
        self.save_token = save_token
        self.save_cookies = save_cookies
        self.cookies_path = cookies_path
        self.save_screenshot = save_screenshot
        self.token = ""
        self.proxy_manager = proxy_manager
        self.use_proxy = True if proxy_manager is not None else False
        self.proxy_scheme = proxy_scheme

    def __repr__(self):
        return (f"{self.__class__.__name__}(url='{self.url}', max_retries={self.max_retries}, "
                f"save_token={self.save_token}, save_cookies={self.save_cookies}, "
                f"cookies_path='{self.cookies_path}', save_screenshot={self.save_screenshot})")

    def load_saved_token(self, name="uzum"):
        """Load saved token from a file."""
        file_path = f"{data_dir}/{token_dir}/token_{name}.json"
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    file_contents = file.read()
                logger.info("Authorization token loaded successfully.")
                return file_contents
            else:
                logger.info("Authorization token does not exist, getting a new one...")
                return None
        except Exception as e:
            logger.error(f"Error loading token: {e}")
            return None

    def save_cookies_with_path(self, driver, path):
        """Save cookies to a specified path."""
        if not os.path.exists(f"{data_dir}/cookies"):
            os.makedirs(f"{data_dir}/cookies")
        try:
            with open(path, 'wb') as file:
                pickle.dump(driver.get_cookies(), file)
            logger.info("Cookies saved successfully.")
        except Exception as e:
            logger.error(f"Error saving cookies: {e}")

    def load_cookies_with_path(self, driver, path):
        """Load cookies from a specified path."""
        try:
            with open(path, 'rb') as file:
                cookies = pickle.load(file)
                for cookie in cookies:
                    driver.add_cookie(cookie)
            logger.info("Cookies loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading cookies: {e}")

    def find_key(self, data, target="authorization"):
        """Recursively search for the target key in nested dictionaries and lists."""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target:
                    # logger.debug(f"Found {target} key with value: '{value}'")
                    if isinstance(value, str) and len(value) > 1:
                        words = value.split()
                        # logger.debug(f"Split value into words: {words}")
                        # Use the same logic as the old working version, but filter out more invalid tokens
                        last_word = words[-1]
                        if (last_word not in ["undefined", "null", "Bearer", "Promise]", "[object"] and 
                            len(last_word) > 5 and 
                            not last_word.startswith('[object')):
                            logger.debug(f"Returning token: '{last_word}'")
                            return last_word  # Return the LAST word like the old version
                result = self.find_key(value, target)
                if result is not None:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self.find_key(item, target)
                if result is not None:
                    return result
        return None

    def validate_token(self, token):
        """Validate the format of the token."""
        logger.debug("Validating token...")
        pattern = re.compile(r'^[A-Za-z0-9\-_\.]+$')  # Adjust based on token format
        return bool(pattern.match(token))

    def process_browser_logs_to_fetch_authorization(self, logs):
        """Process network logs to find and validate the authorization token."""
        for entry in logs:
            try:
                data = json.loads(entry["message"])["message"]
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug(f"Malformed log entry: {e}")
                continue
            for key in ["authorization", "access_token"]:
                token = self.find_key(data, key)
                if token and self.validate_token(token):
                    logger.info(f"Authorization token {token[0:5]}...{token[-5:-1]} received and validated. Proceeding...")
                    return token
        return None

    def extract_subdomain(self, url):
        """Extract subdomain from the URL."""
        start = len("https://") if url.startswith("https://") else 0
        if url.startswith("https://www."):
            start = len("https://www.")
        end = url.find(".", start)
        return url[start:end] if end != -1 else None

    def get_proxy(self, proxy, request_attempts=1, time_out=1.0):
        if request_attempts > 1:
            logger.info(f"Setting sleep time for reconnection: {2 ** (request_attempts - 1)} seconds")
            time.sleep(2 ** (request_attempts - 1))
        if self.proxy_manager:
            if proxy is not None:
                logger.info(f"Setting proxy {proxy.ip}:{proxy.ports.get(self.proxy_scheme)} to pause")
                self.proxy_manager.pause_proxy(proxy.ip, time_out)
            proxy = self.proxy_manager.get_available_proxy(timeout=60)  # Adjust timeout as needed
            logger.debug(f"TokenManager proxy selected: {proxy.ip}:{proxy.ports.get(self.proxy_scheme)}")
            self.use_proxy = True
        if not proxy:
            logger.warning("No available proxies to use for the connection.")
            self.use_proxy = False
        return proxy

    def init_driver(self, proxy=None):
        """Initialize Chrome WebDriver with anti-detection measures and Docker compatibility."""
        chrome_options = Options()
        
        # Keep it simple like the old working version
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        
        # Essential Docker options only
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Essential anti-detection (same as old version)
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--ignore-certificate-errors")
        
        # Basic display options (same as old version)
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1280,1024')

        # Handle proxy configuration
        if proxy is not None:
            logger.info("Adding proxy extension...")
            ext_path = self.proxy_manager.create_proxy_auth_extension(proxy)
            if ext_path:
                try:
                    if ext_path.endswith('proxy_auth_extension.zip'):
                        ext_path = ext_path.split('proxy_auth_extension.zip')[0]
                    chrome_options.add_argument(f"--load-extension={ext_path}")
                    logger.info(f"Added proxy authentication extension for proxy {proxy.ip}")
                except Exception as e:
                    logger.error(f"Extension error: {e}")
                logger.info(f"Using proxy: {proxy.ip}")
            else:
                logger.warning(f"Failed to create proxy authentication extension for proxy {proxy.ip}")

        try:
            # Use webdriver-manager to handle ChromeDriver automatically
            chromedriver_path = ChromeDriverManager().install()
            
            # Fix the common issue with THIRD_PARTY_NOTICES.chromedriver path
            if chromedriver_path.endswith('THIRD_PARTY_NOTICES.chromedriver'):
                chromedriver_path = chromedriver_path.replace('THIRD_PARTY_NOTICES.chromedriver', 'chromedriver')
            
            # Ensure the chromedriver has execute permissions
            os.chmod(chromedriver_path, 0o755)
            
            service = Service(chromedriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
        except Exception as e:
            logger.warning(f"webdriver-manager failed: {e}, trying fallback options")
            
            # Level 2: Try system ChromeDriver paths
            fallback_paths = [
                '/usr/bin/chromedriver',                 # System path
                '/usr/local/bin/chromedriver',           # Alternative system path
                '/opt/chromedriver',                     # Docker alternative
            ]
            
            driver = None
            for chromedriver_path in fallback_paths:
                if os.path.exists(chromedriver_path):
                    try:
                        logger.info(f"Trying fallback ChromeDriver: {chromedriver_path}")
                        os.chmod(chromedriver_path, 0o755)
                        service = Service(chromedriver_path)
                        driver = webdriver.Chrome(service=service, options=chrome_options)
                        logger.info(f"Successfully using fallback ChromeDriver: {chromedriver_path}")
                        break
                    except Exception as fallback_error:
                        logger.warning(f"Fallback ChromeDriver {chromedriver_path} failed: {fallback_error}")
                        continue
            
            # Level 3: Last resort - try system ChromeDriver without explicit path
            if driver is None:
                logger.warning("All fallback ChromeDrivers failed, trying system PATH")
                driver = webdriver.Chrome(options=chrome_options)
        
        return driver

    def save_screenshot(self, driver, filename):
        """Save screenshot for debugging purposes."""
        if not self.save_screenshot:
            return
        
        try:
            screenshot_dir = f"{data_dir}/screenshots"
            if not os.path.exists(screenshot_dir):
                os.makedirs(screenshot_dir)
            
            screenshot_path = os.path.join(screenshot_dir, filename)
            driver.save_screenshot(screenshot_path)
            logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}")

    def solve_captcha(self, driver):
        """Enhanced captcha solving with multiple strategies."""
        try:
            # Strategy 1: Direct captcha element detection
            captcha_selectors = [
                ".smart-captcha",
                "[data-testid='captcha']",
                ".captcha-container",
                "#captcha",
                ".yandex-captcha"
            ]
            
            for selector in captcha_selectors:
                try:
                    captcha = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    logger.info(f"Found captcha with selector: {selector}")
                    
                    # Try ActionChains for better interaction
                    actions = ActionChains(driver)
                    actions.move_to_element(captcha).click().perform()
                    logger.info("Captcha clicked with ActionChains")
                    time.sleep(3)
                    return True
                    
                except Exception:
                    continue
            
            # Strategy 2: Check for iframes with captcha
            try:
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in iframes:
                    try:
                        driver.switch_to.frame(iframe)
                        captcha = driver.find_element(By.CSS_SELECTOR, ".smart-captcha")
                        captcha.click()
                        logger.info("Captcha clicked inside iframe")
                        driver.switch_to.default_content()
                        time.sleep(3)
                        return True
                    except Exception:
                        driver.switch_to.default_content()
                        continue
                        
            except Exception as e:
                logger.debug(f"Iframe captcha strategy failed: {e}")
            
            # Strategy 3: Fallback - look for any clickable element that might be captcha
            try:
                captcha = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[contains(@class, 'captcha') or contains(@id, 'captcha')]"))
                )
                captcha.click()
                logger.info("Captcha clicked with fallback xpath")
                time.sleep(3)
                return True
                
            except Exception:
                pass
                
            logger.warning("Could not find any captcha elements with any strategy")
            return False
            
        except Exception as e:
            logger.error(f"Error in captcha solving: {e}")
            return False

    def get_token_instance(self, save_logs: bool = False) -> str:
        """
        Retrieve an authorization token by navigating to a URL and processing network logs.

        Returns:
            str: The authorization token if found, else None.
        """

        def get_response(driver):
            driver.get(self.url)

            # Wait until the page is fully loaded
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Save screenshot for debugging if enabled
            if self.save_screenshot:
                self.save_screenshot(driver, f"page_load_{int(time.time())}.png")

            # Check if captcha page is shown
            try:
                WebDriverWait(driver, 20).until(
                    EC.title_contains("Are you not a robot?"))
                
                # Use enhanced captcha solving
                if self.solve_captcha(driver):
                    logger.info("Captcha solved successfully")
                else:
                    logger.warning("Failed to solve captcha with all strategies")
                    
            except Exception as e:
                logger.debug(f"No captcha detected or different page structure: {e}")

            # Wait for the main page to load
            WebDriverWait(driver, 20).until(
                EC.title_contains("Uzum Market"))

            # Save screenshot after captcha if enabled
            if self.save_screenshot:
                self.save_screenshot(driver, f"after_captcha_{int(time.time())}.png")

            # Wait for performance logs to be available
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script(
                    "return window.performance.getEntriesByType('resource').length > 0")
            )
            
            # # Give more time for the page to fully initialize and authenticate
            # # The old undetected_chromedriver might have been handling this differently
            # logger.debug("Waiting for page to fully initialize...")
            # time.sleep(1)  # Longer initial wait like the old version
            
            # # Try to trigger any remaining authentication by interacting with the page
            # try:
            #     # Scroll to trigger any lazy-loaded authentication
            #     driver.execute_script("window.scrollTo(0, 100);")
            #     time.sleep(2)
            #     driver.execute_script("window.scrollTo(0, 0);")
            #     time.sleep(3)
            # except Exception as e:
            #     logger.debug(f"Page interaction failed: {e}")

            return driver.get_log("performance")

        proxy = None
        token = None
        attempt_count = 0
        driver = None

        while attempt_count <= self.max_retries:
            try:
                # self.url = "https://httpbin.org/ip"
                attempt_count += 1
                proxy = self.get_proxy(proxy, attempt_count)
                driver = self.init_driver(proxy)
                logs = get_response(driver)
                # print(driver.page_source)
                # break
                if logs:
                    if self.save_cookies:
                        self.save_cookies_with_path(driver, f"{data_dir}/{self.cookies_path}")
                    if save_logs:
                        with open(f"{data_dir}/network_logs.json", 'w', encoding='utf-8') as json_file:
                            json.dump(logs, json_file, ensure_ascii=False, indent=4)
                            logger.info(f"Network logs saved to: {data_dir}/network_logs.json")

                    logger.info("Network logs received by chromedriver. Processing...")
                    token = self.process_browser_logs_to_fetch_authorization(logs)
                    if token is not None:
                        if self.save_token:
                            subdomain = self.extract_subdomain(self.url)

                            # Ensure the data directory exists
                            token_directory = f"{data_dir}/{token_dir}"
                            if not os.path.exists(token_directory):
                                os.makedirs(token_directory)

                            with open(f"{token_directory}/token_{subdomain}.json", 'w', encoding='utf-8') as file:
                                json.dump(token, file, ensure_ascii=False, indent=4)
                        break
                    else:
                        logger.info("No authorization token received. Retrying...")
                else:
                    logger.warning(f"Logs were not captured in attempt number: {attempt_count}")
            except ProxyUnavailableError as e:
                logger.error(f"Proxy is unavailable: {e}")
                break
            except Exception as e:
                logger.error(f"Failed during Authorization token request: {e}")
            finally:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception as e:
                        logger.error(f"Error during driver quit in get_token_instance: {e}")
        if token is None:
            logger.info(f"Couldn't retrieve an authorization token after {attempt_count} attempts.")
        self.token = token
        return token

    def get_token(self):
        """Return token or fetch one if token not fetched yet"""
        return self.token if self.token != "" else self.get_token_instance()


if __name__ == "__main__":
    pm = ProxyManager.from_json_file(proxy_dir)
    token_manager = TokenManager(proxy_manager=pm, save_token=True)
    token = token_manager.get_token_instance()
    if token is not None:
        logger.info(f"Token received: {token[0:5]}...{token[-5:-1]}")
    else:
        logger.info("Token not found!")
