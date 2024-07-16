import time
from datetime import datetime
import os
import glob
import csv
import logging
import sys
from typing import List, Any

import root_categories
import product_ids
import product_parser

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

main_url = "https://uzum.uz/ru"
graphql_url = "https://graphql.uzum.uz/"
root_categories_req_url = "https://api.uzum.uz/api/main/root-categories?eco=false"
product_api_url = "https://api.uzum.uz/api/v2/product/"

token_manager = None
auth_token = None

data_dir = "data"


def save_csv(file: List[Any], file_name: str, sub_dir: str = "", add_date_time: bool = True) -> None:
    """
    Save the given data to a CSV file.

    Args:
        file (List[Any]): Data to be saved.
        file_name (str): Name of the file.
        sub_dir (str, optional): Sub-directory within the data directory.
        add_date_time (bool, optional): Whether to append the current datetime to the file name.
    """
    dir_path = f"{data_dir}/{sub_dir}"
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    orig_file_name = file_name
    if add_date_time:
        file_name = f'{file_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    with open(f'{dir_path}/{file_name}.csv', 'w', newline='') as write_file:
        writer = csv.writer(write_file)
        writer.writerow(file)
        logger.info(f"{orig_file_name} saved to a .csv file in {
                    data_dir}/{sub_dir}")


def load_last_saved_csv(directory: str, name: str) -> List[int]:
    """
    Load the last saved CSV file from the specified directory.

    Args:
        directory (str): The directory containing the CSV files.
        name (str): The base name of the CSV files.

    Returns:
        List[int]: List of integers read from the CSV file.
    """
    try:
        list_of_files = glob.glob(os.path.join(directory, f'{name}_*.csv'))
        if not list_of_files:
            raise FileNotFoundError(
                "No csv files found in the directory/category.")

        latest_file = max(list_of_files, key=os.path.getctime)

        with open(latest_file, newline='') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                int_list = [int(item) for item in row]
        return int_list
    except Exception as e:
        logging.error(f'Failed to load the last saved csv file: {e}')
        return None


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
        if leaf_categories:
            save_csv(leaf_categories, 'leaf_categories', 'category_ids')
        else:
            raise AttributeError("Leaf categories not found")

        logger.info("Retrieving IDs...")
        p_ids = product_ids.fetch_product_ids_by_categories(
            leaf_categories)
        if p_ids is None:
            raise FileNotFoundError("Failed to retrieve product IDs.")

        logger.info('Parsing products...')
        products, failed_products_ids = product_parser.fetch_products(p_ids)
        logger.info(f"Products fetched: {len(products)}; failed count: {
                    len(failed_products_ids)}")

    except Exception as e:
        logger.error(f"Could not fetch data: {e}. Exiting...")
    finally:
        end_time = time.time()
        logger.info(f"Total execution time: {
                    end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    try:
        fetch_data()
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->main: {e}")
