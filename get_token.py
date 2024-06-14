import undetected_chromedriver as uc
# from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import json
import pprint
import os
from datetime import datetime
import pickle
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


def load_saved_token(name="uzum"):
    file_path = f"token/token_{name}.txt"

    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            file_contents = file.read()
        logger.info("Authorization token loaded successfully.")
        return (file_contents)
    else:
        logger.info("Authorization token does not exist, getting a new one...")
        return None


def save_cookies_with_path(driver, path):
    """Save cookies to a specified path."""
    with open(path, 'wb') as file:
        pickle.dump(driver.get_cookies(), file)


def load_cookies_with_path(driver, path):
    """Load cookies from a specified path."""
    with open(path, 'rb') as file:
        cookies = pickle.load(file)
        for cookie in cookies:
            driver.add_cookie(cookie)


def get_token_instance(url="https://uzum.uz/ru", max_retries=0, save_token=False, save_cookies=False, cookies_path="cookies/cookies.pkl") -> str:
    """
    Retrieve an authorization token by navigating to a URL and processing network logs.

    Args:
        service (Service, optional): Selenium Service object. Defaults to None.
        url (str, optional): URL to navigate to. Defaults to "https://uzum.uz/ru".
        save_token (bool, optional): Whether to save the token to a file. Defaults to False.
        save_cookies (bool, optional): Whether to save cookies to a file. Defaults to False.
        cookies_path (str, optional): Path to save cookies. Defaults to "cookies.pkl".

    Returns:
        str: The authorization token if found, else None.
    """
    chrome_options = uc.ChromeOptions()
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # # Initialize the ChromeDriver service
    # if service is None:
    # #     service = Service()
    # service = Service(ChromeDriverManager().install())
    # driver = uc.Chrome(service=service, options=chrome_options)
    driver = uc.Chrome(options=chrome_options)

    def find_key(data, target="authorization"):
        """Recursively search for the target key in nested dictionaries and lists."""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target:
                    if len(value) > 1:
                        words = value.split()
                        if words[-1] != "undefined":
                            return words[-1]
                result = find_key(value, target)
                if result is not None:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = find_key(item, target)
                if result is not None:
                    return result
        return None

    def process_browser_logs_for_network_events(logs):
        """Process network logs to find the authorization token."""
        for entry in logs:
            data = json.loads(entry["message"])["message"]
            token = find_key(data, "authorization")
            if token is not None:
                logger.info("Authorization token received. Proceeding...")
                return token

    def extract_subdomain(url):
        """Extract subdomain from the URL."""
        start = len("https://") if url.startswith("https://") else 0
        if url.startswith("https://www."):
            start = len("https://www.")
        end = url.find(".", start)
        return url[start:end] if end != -1 else None

    token = None
    attempt_count = 0
    try:
        while attempt_count <= max_retries:
            driver.get(url)

            if save_cookies:
                save_cookies_with_path(driver, cookies_path)

            # Wait for performance logs to be available
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script(
                    "return window.performance.getEntriesByType('resource').length > 0")
            )

            logs = driver.get_log("performance")

            if logs:
                logger.info("Network logs received. Processing...")
                token = process_browser_logs_for_network_events(logs)
                if token is not None:
                    if save_token and token:
                        subdomain = extract_subdomain(url)

                        # Ensure the data directory exists
                        token_directory = "token"
                        if not os.path.exists(token_directory):
                            os.makedirs(token_directory)

                        out_name = os.path.join(token_directory, f"token_{
                                                subdomain}.txt")
                        with open(out_name, "wt") as out:
                            pprint.pprint(token, stream=out)
                    break
                else:
                    logger.info("No authorization token received. Retrying...")
            else:
                logger.warning(f"Logs were not captured in attempt: {
                               attempt_count}")
            attempt_count += 1
            time.sleep(attempt_count)
    except Exception as e:
        logger.error(f"Error in get_token_instance: {e}")
    finally:
        try:
            for handle in driver.window_handles[:-1]:
                driver.switch_to.window(handle)
                print("look. %s is closing" % driver.current_url)
                # sleep(1)
                driver.close()
            driver.close()
            driver.quit()
        except Exception as e:
            logger.error(f"Error during driver quit: {e}")
    if token is None:
        logger.info(f"Couldn't retrieve an authorization token after {
                    max_retries + 1} attempts.")
    return token


if __name__ == "__main__":
    # service = Service(ChromeDriverManager().install())
    token = get_token_instance()
    if token is not None:
        logger.info(f"Token received:\n{token}")
    else:
        logger.info("Token not found!")
