import time
from datetime import datetime
import os
import glob
import csv
import logging
import logging.config

import sys
from typing import List, Any

import root_categories
import product_ids
import product_parser
import save_and_load_data
import configparser

# Configure logging
logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()


config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
brands_dir = config.get('storage', 'brands_sub_dir')
product_ids_dir = config.get('storage', 'product_ids_sub_dir')
products_dir = config.get('storage', 'products_sub_dir')

data_dir: str = "data"


def fetch_data() -> None:
    """
    Fetch data from the API and handle errors, retries, and backoff.

    This function fetches root categories, leaf categories, product IDs, and product details.
    """
    start_time = time.time()
    try:
        rc = root_categories.get_root_categories()
        if rc is None:
            raise FileNotFoundError("Failed to load root-categories.")

        leaf_categories = root_categories.find_leaf_categories(rc)
        if not leaf_categories:
            raise AttributeError("Leaf categories not found")

        logger.info("Retrieving IDs...")
        # p_ids = product_ids.fetch_product_ids_by_categories(leaf_categories)
        # if p_ids is None:
        #     raise FileNotFoundError("Failed to retrieve product IDs.")
        p_ids = save_and_load_data.load_last_saved_csv(f'{data_dir}/{product_ids_dir}', 'product_ids')

        logger.info('Parsing products...')
        products, failed_products_ids = product_parser.fetch_products(p_ids)
        logger.info(f"Products fetched: {len(products)}; failed count: {len(failed_products_ids)}")

    except Exception as e:
        logger.error(f"Could not fetch data: {e}. Exiting...")
    finally:
        end_time = time.time()
        logger.info(f"Total execution time: {end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    try:
        fetch_data()
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->main: {e}")
