import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import logging
import json
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


main_url = "https://uzum.uz/ru"
main_url = "https://uzum.uz/ru/product/smartfon-xiaomi-redmi-993951?skuid=2805577"

auth_token = get_token_with_retry(url=main_url)
if auth_token is None:
    logger.error("Can't retrieve authorization token! Shutting down...")
    exit()

# Initialize undetected_chromedriver
options = uc.ChromeOptions()

# options.headless = False  # Run Chrome in GUI mode to simulate a real user

# Disable WebRTC to prevent access to STUN servers
options.add_argument("--disable-webrtc")
options.add_argument("--disable-media-stream")
options.add_argument("--disable-features=WebRTC-H264WithOpenH264FFmpeg")


# options.add_argument('--no-sandbox')
# options.add_argument('--enable-javascript')
# options.add_argument('--disable-gpu')
# user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15'
# options.add_argument('User-Agent={0}'.format(user_agent))
# # options.add_experimental_option(
# #     "excludeSwitches", ["enable-automation"])
# # options.add_experimental_option('useAutomationExtension', True)

driver = uc.Chrome(options=options)


def fetch_data_with_retry(driver, script, max_tries=5):
    """Retry fetching data with a maximum number of attempts."""
    attempt = 0
    while attempt < max_tries:
        json_data = driver.execute_script("return " + script)
        if json_data is not None:
            return json_data
        else:
            logger.info("Failed to retrieve JSON data. Retrying...")
        attempt += 1
        time.sleep(2)
    return None


try:
    # Open the main URL to initialize any necessary session or cookies
    driver.get(main_url)
    time.sleep(5)  # Wait for the page to load

    # Make the request to the API endpoint
    api_url = "https://api.uzum.uz/api/v2/product/993951"

    # Use JavaScript to make the GET request and retrieve the JSON response
    script = f"""
        console.log('Executing fetch request...');
        const url = '{api_url}';
        const headers = {{
            "authority": "api.uzum.uz",
            "Accept": "application/json",
            "Authorization": "Bearer {auth_token}",
            "Content-Type": "application/json",
            "Referer": "https://uzum.uz/"
        }};
        console.log('URL:', url);
        console.log('Headers:', headers);
        return fetch(url, {{ method: 'GET', headers: headers }})
            .then(response => {{
                console.log('Fetch response status:', response.status);
                if (!response.ok) {{
                    throw new Error('Network response was not ok');
                }}
                return response.json();
            }})
            .then(data => {{
                console.log('Fetch success:', data);
                return data;
            }})
            .catch(error => {{
                console.error('Fetch error:', error);
                return null;
            }});
    """

    # Execute the script in the browser and retrieve the data
    json_data = fetch_data_with_retry(driver, script)
    time.sleep(50)
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
finally:
    # Close the browser
    driver.close()
    driver.quit()
