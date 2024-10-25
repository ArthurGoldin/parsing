import time
import logging
import logging.config

import sys
from typing import List, Any
import argparse

import root_categories
# import product_ids
# import product_parser
from save_and_load_data import save_to_file, load_json
import configparser
from token_manager import TokenManager
import send_data_to_db

from ids_fetcher import IdsFetcher
from product_fetcher import ProductFetcher

# Configure logging
try:
    logging.config.fileConfig('configs/logging.conf')
    logger = logging.getLogger('system_check')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")


config = configparser.ConfigParser()
config.read('configs/app.conf')

# Load Default Configuration from JSON
default_config = load_json('configs/default_config.json')


def get_config(section: str, option: str) -> Any:
    """
    Retrieve configuration value with fallback to default if missing.
    """
    if config.has_option(section, option):
        return config.get(section, option)
    else:
        default = default_config.get(section, {}).get(option)
        if default is not None:
            logger.warning(f"Missing configuration '{option}' in section '{section}'. Using default: '{default}'")
            return default
        else:
            logger.error(f"Missing configuration '{option}' in section '{section}' and no default provided.")
            sys.exit(1)


def validate_config():
    """
    Validates that all required configuration sections and options are present.
    Exits the program if validation fails.
    """
    required_sections = default_config.keys()
    for section in required_sections:
        if not config.has_section(section):
            logger.warning(f"Missing required configuration section: '{section}'. Using defaults for this section.")
        for option in default_config[section]:
            if not config.has_option(section, option):
                logger.warning(f"Missing configuration '{option}' in section '{section}'. Using default.")


# Validate configurations
validate_config()

# Retrieve storage configurations
data_dir = get_config('storage', 'data_directory')
brands_dir = get_config('storage', 'brands_sub_dir')
category_ids_dir = get_config('storage', 'category_ids_sub_dir')
check_dir = get_config('storage', 'check_sub_dir')
failed_categories_dir = get_config('storage', 'failed_categories_sub_dir')
images_dir = get_config('storage', 'images_sub_dir')
product_ids_dir = get_config('storage', 'product_ids_sub_dir')
products_dir = get_config('storage', 'products_sub_dir')
root_categories_dir = get_config('storage', 'root_categories_sub_dir')
token_dir = get_config('storage', 'token_sub_dir')
def_pr_name = get_config('storage', 'def_product_name')

# Retrieve URLs configurations
main_url = get_config('urls', 'main_url')
graphql_url = get_config('urls', 'graphql_url')
root_categories_req_url = get_config('urls', 'root_categories_req_url')
product_api_url = get_config('urls', 'product_api_url')


def run_system_check(host_name="localhost"):
    """
    Checks all modules.
    """
    start_time = time.time()
    logger.info('Starting a system check...')
    res_stats = {}

    try:
        logger.info('Checking token_manager...')
        token_manager = TokenManager(
            url=main_url,
            max_retries=5,
            save_token=False,
            save_cookies=False
        )
        auth_token = token_manager.get_token_instance()
        if not auth_token:
            res_stats["auth_token"] = "FAILED"
        else:
            res_stats["auth_token"] = "PASSED"
        logger.info(f'auth_token: {res_stats["auth_token"]}')
    except Exception as e:
        res_stats["auth_token"] = "ERROR"
        logger.error(f"Error in token_manager: {e}")

    try:
        logger.info('Checking root_categories...')
        rc = root_categories.get_root_categories(save_data=False)
        if rc is None:
            res_stats["root_categories"] = "FAILED"
        else:
            res_stats["root_categories"] = "PASSED"
        logger.info(f'root_categories: {res_stats["root_categories"]}')
    except Exception as e:
        res_stats["root_categories"] = "ERROR"
        logger.error(f"Error in root_categories: {e}")

    try:
        logger.info('Checking leaf_categories...')
        leaf_categories = root_categories.find_leaf_categories(rc, save_data=False)
        if not leaf_categories:
            res_stats["leaf_categories"] = "Failed"
        else:
            res_stats["leaf_categories"] = "PASSED"
        logger.info(f'leaf_categories: {res_stats["leaf_categories"]}')
    except Exception as e:
        res_stats["leaf_categories"] = "ERROR"
        logger.error(f"Error in leaf_categories: {e}")

    try:
        logger.info('Checking product_ids...')
        product_ids = IdsFetcher()
        p_ids = product_ids.fetch_product_ids_by_categories([leaf_categories[0]] if leaf_categories else [10], save_data=False)  # change to other default category ID if necessary
        if p_ids is None:
            res_stats["product_ids"] = "FAILED"
        else:
            res_stats["product_ids"] = "PASSED"
        logger.info(f'product_ids: {res_stats["product_ids"]}')
    except Exception as e:
        res_stats["product_ids"] = "ERROR"
        logger.error(f"Error in product_ids: {e}")

    try:
        logger.info('Checking product_parser...')
        product_parser = ProductFetcher()
        # products, failed, status = product_parser.fetch_products([p_ids[0]] if p_ids else [1106551], save_data=False)  # change to other default product ID if necessary
        status = product_parser.fetch_products([p_ids[0]] if p_ids else [1106551], save_data=False)
        if status != 0:
            res_stats["product_parser"] = "FAILED"
        else:
            res_stats["product_parser"] = "PASSED"
        logger.info(f'product_parser: {res_stats["product_parser"]}')
    except Exception as e:
        res_stats["product_parser"] = "ERROR"
        logger.error(f"Error in product_parser: {e}")

    try:
        logger.info('Checking RabbitMQ messaging...')
        message_send_res = send_data_to_db.run_default('configs', def_pr_name, host_name=host_name)
        if not message_send_res:
            res_stats["send_message"] = "FAILED"
        else:
            res_stats["send_message"] = "PASSED"
        logger.info(f'send_message: {res_stats["send_message"]}')
    except Exception as e:
        res_stats["send_message"] = "ERROR"
        logger.error(f"Error in send_message: {e}")

    end_time = time.time()
    logger.info(f"Total execution time: {end_time - start_time:.2f} seconds")

    if res_stats:
        save_to_file(res_stats, 'check_results', 'system_check')
    return res_stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Parser modules checker')
    parser.add_argument('host_name', metavar='STR', type=str, nargs='?',
                        help='a name of the rabbitmq server host for messaging')
    args = parser.parse_args()
    val = args.host_name

    try:
        results = run_system_check(val)
        # Determine exit code based on results
        if all(status == "PASSED" for status in results.values()):
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->system_check: {e}")
        sys.exit(1)
