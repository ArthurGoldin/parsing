from typing import Tuple
import os
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
from proxy_manager import Proxy, ProxyManager


current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

# Configure logging
try:
    logging.config.fileConfig(logging_config_path)
    logger = logging.getLogger('brands_crawler')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

config = configparser.ConfigParser()
config.read(config_path)

data_dir = os.path.join(current_dir, config.get('storage', 'data_directory'))
brands_dir = config.get('storage', 'brands_sub_dir')
proxy_dir = config.get('storage', 'proxy_dir')


def get_proxy(
        proxy_manager: ProxyManager,
        proxy: Proxy,
        request_attempts: int = 0,
        time_out: float = 1.0,
        proxy_scheme: str = 'http'
) -> Tuple[Proxy, bool]:
    if request_attempts > 0:
        logger.info(f"Stetting sleep time for reconnection: {2 ** request_attempts} seconds")
        time.sleep(2 ** request_attempts)
    if proxy_manager:
        if proxy is not None:
            logger.info(f"Setting proxy {proxy.ip}:{proxy.ports.get(proxy_scheme)} to pause")
            proxy_manager.pause_proxy(proxy.ip, time_out)
        proxy = proxy_manager.get_available_proxy(timeout=60)  # Adjust timeout as needed
        logger.debug(f"TokenManager proxy selected: {proxy.ip}:{proxy.ports.get(proxy_scheme)}")
    if not proxy:
        logger.warning("No available proxies to use for the connection.")
    return proxy


def init_driver(proxy: Proxy = None, proxy_manager: ProxyManager = None, proxy_scheme: str = 'http') -> uc.Chrome:
    chrome_options = uc.ChromeOptions()
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    # Added for Docker (needed?)
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Added while implementing proxy
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--ignore-certificate-errors")

    # chrome_options.add_argument('--remote-debugging-port=9222')  # Use a fixed port
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280,1024')

    if proxy is not None and proxy_manager is not None:
        logger.info("Adding proxy extension...")
        ext_path = proxy_manager.create_proxy_auth_extension(proxy)
        if ext_path:
            # chrome_options.add_extension(ext_path)
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

    return uc.Chrome(options=chrome_options)


def fetch_html(proxy_manager: ProxyManager, url: str, max_retries: int = 5) -> Optional[str]:
    """
    Fetch the HTML content from the given URL using Selenium.

    Args:
        url (str): The URL to fetch the HTML content from.
        max_retries (int): The maximum number of retry attempts.

    Returns:
        Optional[str]: The fetched HTML content, or None if fetching fails.
    """

    def get_response(driver):
        driver.get(url)

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[@id='filters']//ul")
                )
            )
        except TimeoutException:
            logger.warning("XPath not found within the time limit. Proceeding to click buttons.")

    html = None
    driver = None
    attempt_count = 0
    proxy = None
    while attempt_count < max_retries:
        try:
            proxy = get_proxy(proxy_manager, proxy, attempt_count)

            driver = init_driver(proxy, proxy_manager)

            get_response(driver)

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


def get_brands_by_category(proxy_manager: ProxyManager, categories: List[int], url: str = "https://uzum.uz/ru/category/") -> Dict[int, List[str]]:
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
        html_content = fetch_html(proxy_manager, f'{url}{category}')

        if html_content:
            labels = get_brand_labels(html_content)
            if labels:
                logger.info(f"Category {category} has {len(labels)} brands")
            brands_by_category[category] = labels
        else:
            logger.warning(
                f'Failed to fetch HTML content for category {category}')

    return brands_by_category


def get_all_main_categories(proxy_manager: ProxyManager) -> Optional[List[int]]:
    """
    Get all main categories from the root categories.

    Returns:
        Optional[List[int]]: A list of main category IDs, or None if fetching fails.
    """
    rc = root_categories.load_last_saved_root_categories()
    if not rc:
        rc = root_categories.get_root_categories(proxy_manager=proxy_manager)
    if rc:
        main_categories = [main_category['id'] for main_category in rc['payload']]
        return main_categories
    else:
        return None


def run_brands_crawler(proxy_manager: Optional[ProxyManager] = None):
    if proxy_manager is None:
        proxy_manager = ProxyManager().from_json_file(proxy_dir)

    main_categories = get_all_main_categories(proxy_manager)
    logger.info(f"Beginning brands crawling for total {len(main_categories)} categories.")
    logger.debug(main_categories)

    brands_by_category = get_brands_by_category(proxy_manager, main_categories)
    # brands_by_category = get_brands_by_category([10020])

    if brands_by_category:
        # save_dict_to_file(brands_by_category)
        save_to_file(file=brands_by_category, file_name='brands_by_category', file_type='JSON', sub_dir=brands_dir, add_date_time=True, separate_folder=False)
        logger.info(f"Category brands saved to {data_dir}/{brands_dir}.")
    else:
        logger.error("Could not parse brands by categories.")


if __name__ == "__main__":
    run_brands_crawler()
