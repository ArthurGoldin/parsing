
# from datetime import datetime
import os
import time
import logging
import logging.config

import sys
from typing import List, Any

import root_categories
import configparser
from token_manager import TokenManager
from ids_fetcher import IdsFetcher
from product_fetcher import ProductFetcher
from save_and_load_data import load_last_saved_json
from brands_crawler import run_brands_crawler
from proxy_manager import ProxyManager

current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

logs_path = f"{current_dir}/logs"
if not os.path.exists(logs_path):
    os.makedirs(logs_path)

# Check and create app.log if it does not exist
log_file_path = os.path.join(logs_path, "app.log")
if not os.path.exists(log_file_path):
    with open(log_file_path, "w") as log_file:
        log_file.write("")

# Configure logging
try:
    logging.config.fileConfig(logging_config_path)
    logger = logging.getLogger('main')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

config = configparser.ConfigParser()
config.read(config_path)

data_dir = os.path.join(current_dir, config.get('storage', 'data_directory'))
brands_dir = config.get('storage', 'brands_sub_dir')
product_ids_dir = config.get('storage', 'product_ids_sub_dir')
products_dir = config.get('storage', 'products_sub_dir')
root_categories_dir = config.get('storage', 'root_categories_sub_dir')
proxy_dir = config.get('storage', 'proxy_dir')

max_prd_fetching_retries = config.getint('main', 'max_prd_fetching_retries')

if not os.path.exists(data_dir):
    os.makedirs(data_dir)


def fetch_data() -> None:
    """
    Fetch data from the API and handle errors, retries, and backoff.

    This function fetches root categories, leaf categories, product IDs, and product details.
    """
    start_time = time.time()

    token_manager = None
    proxy_manager = None
    try:
        proxy_manager = ProxyManager().from_json_file(proxy_dir)
        token_manager = TokenManager(proxy_manager=proxy_manager)

        rc, rc_s = root_categories.get_all_root_categories(proxy_manager=proxy_manager, token_manager=token_manager)
        if rc is None or rc_s is None:
            raise FileNotFoundError("Failed to load root-categories.")

        # rc_s = load_last_saved_json(f"{data_dir}/{root_categories_dir}", root_categories_dir)
        lc = root_categories.find_leaf_categories(rc_s)
        if not lc:
            raise AttributeError("Leaf categories not found")

        logger.info("Retrieving IDs...")

        ids_fetcher = IdsFetcher(proxy_manager=proxy_manager, token_manager=token_manager)
        p_ids = ids_fetcher.run(lc)
        if p_ids is None:
            raise FileNotFoundError("Failed to retrieve product IDs.")
        # p_ids = save_and_load_data.load_last_saved_json(f'{data_dir}/{product_ids_dir}', 'product_ids')

        brands_by_category = load_last_saved_json(f'{data_dir}/{config.get("storage", "brands_sub_dir")}')
        if not brands_by_category:
            logger.info("No brands stored. Running brands_crawler...")
            run_brands_crawler()

        logger.info('Parsing products...')
        product_fetcher_counter = 0
        ind = 0
        product_fetcher = ProductFetcher(proxy_manager=proxy_manager, token_manager=token_manager)
        product_fetcher_counter += 1
        status, ind = product_fetcher.run(p_ids, ind=ind, retries=max_prd_fetching_retries)

        if status == 0:
            logger.info(f"Successfully processed and fetched {ind} products.")
        else:
            logger.warning(f"Failed tp finish fetching all products. Return status: {status}")
            logger.warning(f"Failed to process and fetch {len(p_ids[ind:])} of {len(p_ids)} products.")
        # products, failed_products_ids, status = product_parser.fetch_products(p_ids)
        # logger.info(f"Products fetched and parsed: {len(products)}; failed IDs count: {len(failed_products_ids)}")

    except Exception as e:
        logger.error(f"Could not fetch data: {e}. Exiting...")
    finally:
        if proxy_manager is not None:
            proxy_manager.shutdown_scheduler()
        end_time = time.time()
        logger.info(f"Total execution time: {end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    try:
        pass
        fetch_data()
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->main: {e}")
