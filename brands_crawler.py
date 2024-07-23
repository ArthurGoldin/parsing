import json
import undetected_chromedriver as uc
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
from typing import List, Dict, Union, Optional

# Configure logging
logging_level = os.getenv('LOGGING_LEVEL', 'INFO').upper()
logging.basicConfig(level=logging_level,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

data_dir: str = "data"


def save_dict_to_file(category_dict: Dict[str, List[str]], directory: str = f"{data_dir}/brands", filename: str = "brands_by_category") -> None:
    """
    Save the dictionary to a file as JSON.

    Args:
        category_dict (Dict[str, List[str]]): The dictionary containing category data.
        directory (str): The directory where the file should be saved.
        filename (str): The base name of the file.

    Returns:
        None
    """
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(f"{directory}/{filename}_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 'w', encoding='utf-8') as file:
        json.dump(category_dict, file, ensure_ascii=False, indent=4)
        logger.info(f"Saved {filename} to {directory}")


def save_html_to_file(html: str, filename: str) -> None:
    """
    Save the HTML content to a file.

    Args:
        html (str): The HTML content to be saved.
        filename (str): The name of the file.

    Returns:
        None
    """
    with open(f"data/{filename}", 'w', encoding='utf-8') as file:
        file.write(html)
        logger.info(f"Saved {filename} to data dir.")


def load_last_saved_dict(directory: str = f"{data_dir}/brands") -> Optional[Dict[str, List[str]]]:
    """
    Load the most recently saved dictionary from the specified directory.

    Args:
        directory (str): The directory to look for JSON files.

    Returns:
        Optional[Dict[str, List[str]]]: The loaded dictionary, or None if loading fails.
    """
    list_of_files = glob.glob(os.path.join(directory, '*.json'))

    if not list_of_files:
        logger.warning(f"No JSON files found in directory {directory}.")
        return None

    latest_file = max(list_of_files, key=os.path.getmtime)

    try:
        with open(latest_file, 'r', encoding='utf-8') as file:
            category_dict = json.load(file)
        logger.info(f"Loaded data from {latest_file}.")
        return category_dict
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from the file {latest_file}.")
        return None


def fetch_html(url: str, max_retries: int = 5) -> Optional[str]:
    """
    Fetch the HTML content from the given URL using Selenium.

    Args:
        url (str): The URL to fetch the HTML content from.
        max_retries (int): The maximum number of retry attempts.

    Returns:
        Optional[str]: The fetched HTML content, or None if fetching fails.
    """

    html = None
    driver = None
    attempt_count = 0

    while attempt_count < max_retries:
        options = uc.ChromeOptions()
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = uc.Chrome(options=options)
        try:
            driver.get(url)

            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     "/html/body/div/main/div/div[2]/div[2]/div[2]/aside/div/div/div/div[1]")
                )
            )
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     "/html/body/div/main/div/div[2]/div[2]/div[2]/aside/div/div/div/div[2]/ul")
                )
            )

            time.sleep(1)
            while True:
                try:
                    buttons = driver.find_elements(
                        By.XPATH, "//span[@data-test-id='button__show-more']")
                    if not buttons:
                        break
                    for button in buttons:
                        driver.execute_script("arguments[0].click();", button)
                        time.sleep(1)

                    time.sleep(2)
                    break
                except Exception as e:
                    logger.error(f"Error clicking 'show more' buttons: {e}")
                    break

            html = driver.page_source

            if html:
                break
            else:
                logger.warning(f"Could not fetch HTML content for category ID {
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


def get_brand_labels(html: str) -> List[str]:
    """
    Extract brand labels from the HTML content.

    Args:
        html (str): The HTML content.

    Returns:
        List[str]: A list of brand labels.
    """
    soup = BeautifulSoup(html, 'html.parser')

    span_elements = soup.find_all('span', {
                                  'class': 'slightly transparent hug title-text', 'data-test-id': 'text__filter-name'})

    brand_section = None
    for span in span_elements:
        if span.get_text(strip=True) == 'Бренд':
            brand_section = span
            break

    if not brand_section:
        logger.warning("Brand section not found")
        return []

    parent_div = brand_section.find_parent('div', class_='filter')

    if not parent_div:
        logger.error("Parent div not found")
        return []

    labels = parent_div.find_all('div', class_='filter-checkbox--label')
    label_texts = [label.get_text(strip=True) for label in labels]

    return label_texts


def get_brands_by_category(categories: List[int], url: str = "https://uzum.uz/ru/category/") -> Dict[int, List[str]]:
    """
    Get brands by category from the specified URL.

    Args:
        categories (List[int]): A list of category IDs.
        url (str): The base URL for categories.

    Returns:
        Dict[int, List[str]]: A dictionary with category IDs as keys and lists of brands as values.
    """
    brands_by_category = {}
    for category in categories:
        html_content = fetch_html(f'{url}{category}')

        if html_content:
            labels = get_brand_labels(html_content)
            if labels:
                logger.info(f"Category {category} has {len(labels)} brands")
            brands_by_category[category] = labels
        else:
            logger.warning(
                f'Failed to fetch HTML content for category {category}')

    return brands_by_category


def get_all_main_categories() -> Optional[List[int]]:
    """
    Get all main categories from the root categories.

    Returns:
        Optional[List[int]]: A list of main category IDs, or None if fetching fails.
    """
    rc = root_categories.load_last_saved_root_categories()
    if not rc:
        rc = root_categories.get_root_categories(
            load_most_recent_if_failed=False)
    if rc:
        main_categories = [main_category['id']
                           for main_category in rc['payload']]
        return main_categories
    else:
        return None


def run_brands_crawler():
    main_categories = get_all_main_categories()
    logger.info(f"Beginning brands crawling for total {
                len(main_categories)} categories.")
    logger.info(main_categories)

    brands_by_category = get_brands_by_category(main_categories)
    # brands_by_category = get_brands_by_category([10012])

    if brands_by_category:
        save_dict_to_file(brands_by_category)
        logger.info(f"Category brands saved to {data_dir}/brands.")
    else:
        logger.error("Could not parse brands by categories.")


if __name__ == "__main__":
    run_brands_crawler()
