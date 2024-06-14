import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import logging
import json
import requests
from get_token import get_token_instance

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


def get_token_with_retry(url, max_tries=5):
    """Retry getting authorization token with a maximum number of attempts."""
    attempt = 0
    while attempt < max_tries:
        auth_token = get_token_instance(url)
        if auth_token is not None:
            return auth_token
        else:
            logger.info("No authorization token received. Retrying...")
        attempt += 1
        time.sleep(2)
    return None


main_url = "https://uzum.uz/ru/"
main_url = "https://uzum.uz/ru/product/993951"

auth_token = get_token_with_retry(url=main_url)
if auth_token is None:
    logger.error("Can't retrieve authorization token! Shutting down...")
    exit()

# Initialize undetected_chromedriver
options = uc.ChromeOptions()
driver = uc.Chrome(options=options)

try:
    # Open the main URL to initialize any necessary session or cookies
    driver.get(main_url)
    time.sleep(5)  # Wait for the page to load

    # Extract cookies and other necessary headers
    cookies = driver.get_cookies()
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "ru-RU",
        "Authorization": f"Bearer {auth_token}",
        "Baggage": "sentry-environment=production,sentry-release=uzum-market%401.25.0,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=40a1da8f98b74671a4904e563e68d171,sentry-sample_rate=0.001,sentry-transaction=product,sentry-sampled=false",
        "Content-Type": "application/json",
        "Origin": "https://uzum.uz",
        "Priority": "u=1, i",
        "Referer": "https://uzum.uz/",
        "Sec-Ch-Ua": "\"Not/A)Brand\";v=\"8\", \"Chromium\";v=\"126\", \"Google Chrome\";v=\"126\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": "\"Windows\"",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Sentry-Trace": "40a1da8f98b74671a4904e563e68d171-86d5c3abb360c71b-0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "X-Iid": "8d8f8d7a-2d63-4668-8655-3e56f88c710c"
    }

    # Convert cookies to a format that can be used with requests
    session_cookies = {cookie['name']: cookie['value'] for cookie in cookies}

    # Close the browser
    driver.quit()

    # Make the request to the API endpoint using requests
    api_url = "https://api.uzum.uz/api/v2/product/993951"

    def fetch_data_with_retry(url, headers, cookies, max_tries=1):
        """Retry fetching data with a maximum number of attempts."""
        attempt = 0
        while attempt < max_tries:
            try:
                response = requests.get(url, headers=headers, cookies=cookies)
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.info(f"Failed to retrieve JSON data. Status code: {
                                response.status_code}. Retrying...")
            except requests.exceptions.RequestException as e:
                logger.error(f"Request exception: {e}. Retrying...")
            attempt += 1
            time.sleep(2)
        return None

    # Fetch the data
    json_data = fetch_data_with_retry(api_url, headers, session_cookies)
    print(f'response = {type(json_data)}')
    if json_data is not None:
        # Save the JSON data to a file
        with open('data.json', 'w', encoding='utf-8') as json_file:
            json.dump(json_data, json_file, ensure_ascii=False, indent=4)
        logger.info("JSON data saved to data.json")
    else:
        logger.error("Failed to retrieve JSON data after multiple attempts")

except Exception as e:
    logger.error(f'Error: {e}')
    # Take a screenshot for debugging
    driver.save_screenshot('error_screenshot.png')
    driver.quit()
finally:
    # Ensure the browser is closed
    if driver.service.process:
        driver.quit()
