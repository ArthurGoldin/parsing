import json
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
import os
import logging
import time
from bs4 import BeautifulSoup
import root_categories
from datetime import datetime
import glob

# Configure logging
logging_level = os.getenv('LOGGING_LEVEL', 'INFO').upper()
logging.basicConfig(level=logging_level,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

data_dir = "data"


def save_dict_to_file(category_dict, directory=f"{data_dir}/brands", filename="brands_by_category"):
    # Ensure the directory exists
    if not os.path.exists(directory):
        os.makedirs(directory)

    # Save the dictionary to a file as JSON
    with open(f"{directory}/{filename}_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 'w', encoding='utf-8') as file:
        json.dump(category_dict, file, ensure_ascii=False, indent=4)


def save_html_to_file(html, filename):
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(html)


def load_last_saved_dict(directory=f"{data_dir}/brands"):
    # Find all JSON files in the directory
    list_of_files = glob.glob(os.path.join(directory, '*.json'))

    if not list_of_files:
        print(f"No JSON files found in directory {directory}.")
        return None

    # Get the latest file by modification time
    latest_file = max(list_of_files, key=os.path.getmtime)

    # Load the dictionary from the latest file
    try:
        with open(latest_file, 'r', encoding='utf-8') as file:
            category_dict = json.load(file)
        print(f"Loaded data from {latest_file}.")
        return category_dict
    except json.JSONDecodeError:
        print(f"Error decoding JSON from the file {latest_file}.")
        return None


def fetch_html(url, max_retries=5):
    options = uc.ChromeOptions()
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    html = None
    driver = None
    attempt_count = 0
    try:
        driver = uc.Chrome(options=options)
        while attempt_count < max_retries:
            driver.get(url)

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Check if the button exists and click it if found
            try:
                show_more_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "(//span[@data-test-id='button__show-more'])[2]"))
                )
                show_more_button.click()
                time.sleep(5)  # Wait for the page to load additional content
            except:
                logger.info("Show more button not found or not clickable")

                # Fetch the updated page source
            html = driver.page_source

            if html:
                break
            else:
                logger.warning(f"Could not fetch html content for category id {
                               url.split('/')[-1]} in attempt number {attempt_count}. Retrying...")
                attempt_count += 1
    except Exception as e:
        logger.error(f'Error fetching HTML: {e}')
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as e:
                logger.error(f'Error during driver quit: {e}')

    return html


def get_brand_labels(html):
    soup = BeautifulSoup(html, 'html.parser')

    # Find all span elements with the relevant class and attribute
    span_elements = soup.find_all('span', {
                                  'class': 'slightly transparent hug title-text', 'data-test-id': 'text__filter-name'})

    # Identify the "Бренд" section
    brand_section = None
    for span in span_elements:
        if span.get_text(strip=True) == 'Бренд':
            brand_section = span
            break

    if not brand_section:
        logger.error("Brand section not found")
        return []

    # Get the parent div that contains the label section
    parent_div = brand_section.find_parent('div', class_='filter')

    if not parent_div:
        logger.error("Parent div not found")
        return []

    # Find all the labels under this parent div
    labels = parent_div.find_all('div', class_='filter-checkbox--label')
    label_texts = [label.get_text(strip=True) for label in labels]

    return label_texts


def get_brands_by_category(categories, url="https://uzum.uz/ru/category/"):
    brands_by_category = {}
    for category in categories:
        html_content = fetch_html(f'{url}{category}')

        if html_content:
            labels = get_brand_labels(html_content)
            if labels:
                logger.info(f"Category {category} has {len(labels)} brands")
            brands_by_category[category] = labels
        else:
            logger.error(
                f'Failed to fetch HTML content for category {category}')

    return brands_by_category


def get_all_main_categories():
    rc = root_categories.load_last_saved_root_categories()
    if not rc:
        rc = root_categories.get_root_categories(
            load_most_recent_if_failed=False)
    if rc:
        main_categories = []
        for main_category in rc['payload']:
            main_categories.append(main_category['id'])
        return main_categories
    else:
        return None


main_categories = get_all_main_categories()
logger.info(f"Beginning brands crawling for total {
            len(main_categories)} categories.")
brands_by_category = get_brands_by_category(main_categories)

if brands_by_category:
    save_dict_to_file(brands_by_category)
    logger.info(f"Category brands saved tp {data_dir}/brands.")
else:
    logger.error("Could not parse brands by categories.")
