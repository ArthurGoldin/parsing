from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import json

url = 'https://uzum.uz/ru'
# Set up Chrome options
options = Options()
options.headless = False  # Run Chrome in GUI mode to simulate a real user

# Disable WebRTC to prevent access to STUN servers
options.add_argument("--disable-webrtc")
options.add_argument("--disable-media-stream")
options.add_argument("--disable-features=WebRTC-H264WithOpenH264FFmpeg")

# Initialize the ChromeDriver service
service = Service(ChromeDriverManager().install())

# Initialize the WebDriver
driver = webdriver.Chrome(service=service, options=options)

# Navigate to the page protected by Cloudflare
driver.get(url)  # Replace with the actual URL


def save_page_json(driver, name: str):
    page_source = driver.page_source
    page_source_json = {
        'page_source': page_source
    }
    with open(name + '.json', 'w', encoding='utf-8') as file:
        json.dump(page_source_json, file, ensure_ascii=False, indent=4)

    # Function to check if CAPTCHA is present


def is_captcha_present(driver):
    print("Detecting CAPTCHA...")
    try:
        WebDriverWait(driver, 5).until(
            EC.frame_to_be_available_and_switch_to_it(
                (By.CSS_SELECTOR,
                 "iframe[title='Widget containing a Cloudflare security challenge']")
            )
        )
        return True
    except Exception as e:
        # print(f"Exception in is_captcha_present: {e}")
        return False


# Function to click CAPTCHA checkbox
def click_captcha_checkbox(driver):
    try:
        captcha_checkbox = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "label.cb-lb"))
        )
        captcha_checkbox.click()
        print("Clicked the CAPTCHA checkbox.")
        return True
    except Exception as e:
        print("Failed to click the CAPTCHA checkbox:", e)
        return False


def wait_for_spinner(driver):
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.ID, "spinner-icon"))
        )
        print(f"Spinner detected")
        time.sleep(4)
        WebDriverWait(driver, 20).until(
            EC.invisibility_of_element_located(
                (By.ID, "spinner-icon"))
        )
        return True
    except Exception as e:
        print(f"Exception in is_spinner_present: {e}")
        return False


# Loop to handle CAPTCHA multiple times if needed
max_attempts = 5
attempts = 0
page_has_captcha = is_captcha_present(driver)

while attempts < max_attempts:
    attempts += 1
    if page_has_captcha:
        save_page_json(driver, 'page_first_captcha')
        print(f"CAPTCHA detected. Attempting to click the CAPTCHA checkbox. Attempt {
              attempts}/{max_attempts}")

        time.sleep(5)
        if click_captcha_checkbox(driver):
            # Wait for CAPTCHA verification to complete
            try:
                spiner_comlpited = wait_for_spinner(driver)
                page_has_captcha = is_captcha_present(driver)
                if not page_has_captcha and spiner_comlpited:
                    print("CAPTCHA verification completed.")
                    break
            except Exception as e:
                print(f"Exception while waiting for CAPTCHA to disappear: {e}")
        else:
            print("Retrying CAPTCHA click...")
    else:
        print("No CAPTCHA detected. Proceeding with further actions.")
        break
    time.sleep(5)  # Adding delay between attempts

# Now perform further actions like scraping, navigating, etc.
# Example: Find an element and print its text
# if page_has_captcha:
time.sleep(20)
try:
    page_title = driver.title
    print(f"Page title: {page_title}")
except Exception as e:
    print("Failed to find or interact with the element:", e)

# Clean up and close the browser
driver.quit()
