import time
import logging
import logging.config

import sys
from typing import List, Any
import argparse

import root_categories
import product_ids
import product_parser
from save_and_load_data import save_to_file
import configparser
from token_manager import TokenManager
import send_data_to_db

# Configure logging
logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()


config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
brands_dir = config.get('storage', 'brands_sub_dir')
product_ids_dir = config.get('storage', 'product_ids_sub_dir')
products_dir = config.get('storage', 'products_sub_dir')
check_dir = config.get('storage', 'check_subdir')
def_pr_name = config.get('storage', 'def_product_name')

main_url = config.get('urls', 'main_url')


def run_system_check(host_name=""):
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
        products = product_parser.fetch_products([p_ids[0]] if p_ids else [1106551], save_data=False)  # change to other default product ID if necessary
        if products is None:
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
        run_system_check(val)
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->system_check: {e}")
