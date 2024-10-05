import logging
import logging.config
import time
import root_categories
import configparser
import undetected_chromedriver as uc
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from save_and_load_data import save_to_file
# from proxy_manager import ProxyManager

# Configure logging
try:
    logging.config.fileConfig('configs/logging.conf')
    logger = logging.getLogger('main')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
brands_dir = config.get('storage', 'brands_sub_dir')


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
    # proxy_manager = ProxyManager.from_json_file('data/proxy/proxy.json')

    while attempt_count < max_retries:
        # proxy = proxy_manager.get_available_proxy()["proxy_address"]["https"]
        # if proxy is not None:
        #     auth_part, proxy_address = proxy.split("@")
        #     username, password = auth_part.split(":")
        #     proxy_host, proxy_port = proxy_address.split(":")
        #     proxy_port = int(proxy_port)
        #     credentials = f"{username}:{password}"
        #     encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

        options = uc.ChromeOptions()
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = uc.Chrome(options=options)
        try:
            driver.get(url)

            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//div[@id='filters']//ul")
                    )
                )
            except TimeoutException:
                logger.warning("XPath not found within the time limit. Proceeding to click buttons.")

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
                logger.warning(f"Could not fetch HTML content for category ID {url.split('/')[-1]} in attempt number {attempt_count}. Retrying...")
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

    span_elements = soup.find_all('span', {'class': 'slightly transparent hug title-text', 'data-test-id': 'text__filter-name'})

    brand_section = None
    for element in span_elements:
        if element.get_text(strip=True) == 'Бренд':
            brand_section = element
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
        rc = root_categories.get_root_categories()
    if rc:
        main_categories = [main_category['id'] for main_category in rc['payload']]
        return main_categories
    else:
        return None


def run_brands_crawler():
    main_categories = get_all_main_categories()
    logger.info(f"Beginning brands crawling for total {
                len(main_categories)} categories.")
    logger.debug(main_categories)

    brands_by_category = get_brands_by_category(main_categories)
    # brands_by_category = get_brands_by_category([10020])

    if brands_by_category:
        # save_dict_to_file(brands_by_category)
        save_to_file(file=brands_by_category, file_name='brands_by_category', file_type='JSON', sub_dir=brands_dir, add_date_time=True, separate_folder=False)
        logger.info(f"Category brands saved to {data_dir}/{brands_dir}.")
    else:
        logger.error("Could not parse brands by categories.")


if __name__ == "__main__":
    run_brands_crawler()
