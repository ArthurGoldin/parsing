import undetected_chromedriver as uc
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import json
import os
import pickle
import logging
import logging.config
import time

# Configure logging
logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()


class TokenManager:
    def __init__(self, url="https://uzum.uz/ru", max_retries=5, save_token=False, save_cookies=False, cookies_path="cookies/cookies.pkl"):
        self.url = url
        self.max_retries = max_retries
        self.save_token = save_token
        self.save_cookies = save_cookies
        self.cookies_path = cookies_path

    def __repr__(self):
        return (f"{self.__class__.__name__}(url='{self.url}', max_retries={self.max_retries}, "
                f"save_token={self.save_token}, save_cookies={self.save_cookies}, "
                f"cookies_path='{self.cookies_path}')")

    def load_saved_token(self, name="uzum"):
        """Load saved token from a file."""
        file_path = f"data/token/token_{name}.json"
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
                    if len(value) > 1:
                        words = value.split()
                        if words[-1] != "undefined":
                            return words[-1]
                result = self.find_key(value, target)
                if result is not None:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self.find_key(item, target)
                if result is not None:
                    return result
        return None

    def process_browser_logs_to_fetch_authorization(self, logs):
        """Process network logs to find the authorization token."""
        for entry in logs:
            data = json.loads(entry["message"])["message"]
            token = self.find_key(data, "authorization")
            if token is not None and len(token) > 10:
                logger.info("Authorization token received. Proceeding...")
                return token
        for entry in logs:
            data = json.loads(entry["message"])["message"]
            token = self.find_key(data, "access_token")
            if token is not None and len(token) > 10:
                logger.info("Authorization token received. Proceeding...")
                return token

    def extract_subdomain(self, url):
        """Extract subdomain from the URL."""
        start = len("https://") if url.startswith("https://") else 0
        if url.startswith("https://www."):
            start = len("https://www.")
        end = url.find(".", start)
        return url[start:end] if end != -1 else None

    def get_token_instance(self, save_logs: bool = False) -> str:
        """
        Retrieve an authorization token by navigating to a URL and processing network logs.

        Returns:
            str: The authorization token if found, else None.
        """
        chrome_options = uc.ChromeOptions()
        chrome_options.set_capability(
            "goog:loggingPrefs", {"performance": "ALL"})
        # Added for Docker (needed?)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        # chrome_options.add_argument('--remote-debugging-port=9222')  # Use a fixed port
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1280,1024')

        token = None
        attempt_count = 0
        driver = None
        try:
            driver = uc.Chrome(options=chrome_options)
            while attempt_count <= self.max_retries:
                driver.get(self.url)

                if self.save_cookies:
                    self.save_cookies_with_path(driver, self.cookies_path)

                # Wait until the page is fully loaded
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )

                WebDriverWait(driver, 20).until(
                    EC.title_contains("Uzum Market"))

                # Wait for performance logs to be available
                WebDriverWait(driver, 20).until(
                    lambda d: d.execute_script(
                        "return window.performance.getEntriesByType('resource').length > 0")
                )

                logs = driver.get_log("performance")

                if logs:
                    if save_logs:
                        with open('data/network_logs.json', 'w', encoding='utf-8') as json_file:
                            json.dump(logs, json_file, ensure_ascii=False, indent=4)
                            logger.info("Network logs saved to: data/network_logs.json")

                    logger.info(
                        "Network logs received by chromedriver. Processing...")
                    token = self.process_browser_logs_to_fetch_authorization(
                        logs)
                    if token is not None:
                        if self.save_token:
                            subdomain = self.extract_subdomain(self.url)

                            # Ensure the data directory exists
                            token_directory = "data/token"
                            if not os.path.exists(token_directory):
                                os.makedirs(token_directory)

                            with open(f"{token_directory}/token_{subdomain}.json", 'w', encoding='utf-8') as file:
                                json.dump(token, file, ensure_ascii=False, indent=4)
                        break
                    else:
                        logger.info("No authorization token received. Retrying...")
                else:
                    logger.warning(f"Logs were not captured in attempt number: {attempt_count}")
                attempt_count += 1
                time.sleep(attempt_count)
        except Exception as e:
            logger.error(f"Error in get_token_instance: {e}")
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception as e:
                    logger.error(f"Error during driver quit in get_token_instance: {e}")
            if token is None:
                logger.info(f"Couldn't retrieve an authorization token after {self.max_retries + 1} attempts.")
        return token


if __name__ == "__main__":
    token_manager = TokenManager(save_token=True)
    token = token_manager.get_token_instance()
    if token is not None:
        logger.info(f"Token received:\n{token[0:5]}...{token[-5:-1]}")
    else:
        logger.info("Token not found!")
