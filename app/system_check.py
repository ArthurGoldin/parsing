import time
import logging
import logging.config
import os
import sys
from typing import List, Any
import argparse

import root_categories
from save_and_load_data import save_to_file, load_json
import configparser
from token_manager import TokenManager
from proxy_manager import ProxyManager
# import send_data_to_db

from ids_fetcher import IdsFetcher
from product_fetcher import ProductFetcher

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
    logger = logging.getLogger('system_check')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

config = configparser.ConfigParser()
config.read(config_path)

data_dir = os.path.join(current_dir, config.get('storage', 'data_directory'))
if not os.path.exists(data_dir):
    os.makedirs(data_dir)

# Load Default Configuration from JSON
default_config = load_json(f"{current_dir}/configs/default_config.json")


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
# data_dir = get_config('storage', 'data_directory')
# data_dir = os.path.join(current_dir, config.get('storage', 'data_directory'))
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
proxy_dir = config.get('storage', 'proxy_dir')

# Retrieve URLs configurations
main_url = get_config('urls', 'main_url')
graphql_url = get_config('urls', 'graphql_url')
root_categories_req_url = get_config('urls', 'root_categories_req_url')
product_api_url = get_config('urls', 'product_api_url')

broker_host = get_config('broker', 'host')
broker_port = get_config('broker', 'port')


def run_system_check(host_name=broker_host, port=broker_port):
    """
    Checks all modules.
    """
    start_time = time.time()
    logger.info('Starting a system check...')
    res_stats = {}

    token_manager = None
    proxy_manager = None
    p_ids = None
    leaf_categories = None
    rc = None
    try:
        proxy_manager = ProxyManager().from_json_file(proxy_dir)
        try:
            logger.info('Checking token_manager...')
            token_manager = TokenManager(proxy_manager=proxy_manager)
            auth_token = token_manager.get_token_instance()
            if not auth_token:
                res_stats["auth_token"] = "FAILED"
            else:
                res_stats["auth_token"] = "PASSED"
            logger.info(f"auth_token: {res_stats['auth_token']}")
        except Exception as e:
            res_stats["auth_token"] = "ERROR"
            logger.error(f"Error in token_manager: {e}")

        try:
            logger.info('Checking root_categories...')
            rc = root_categories.get_root_categories(proxy_manager=proxy_manager, save_data=False)
            if rc is None:
                res_stats["root_categories"] = "FAILED"
            else:
                res_stats["root_categories"] = "PASSED"
            logger.info(f"root_categories: {res_stats['root_categories']}")
        except Exception as e:
            res_stats["root_categories"] = "ERROR"
            logger.error(f"Error in root_categories: {e}")

        try:
            logger.info('Checking category tree request with GraphQl...')
            ct = root_categories.get_category_tree(proxy_manager=proxy_manager, token_manager=token_manager, save_data=False)
            if ct is None:
                res_stats["root_categories(GraphQL request)"] = "FAILED"
            else:
                res_stats["root_categories(GraphQL request)"] = "PASSED"
            logger.info(f"root_categories(GraphQL request): {res_stats['root_categories(GraphQL request)']}")
        except Exception as e:
            res_stats["root_categories(GraphQL request)"] = "ERROR"
            logger.error(f"Error in root_categories(GraphQL request): {e}")

        try:
            logger.info('Checking leaf_categories...')
            leaf_categories = root_categories.find_leaf_categories(rc, save_data=False)
            if not leaf_categories:
                res_stats["leaf_categories"] = "Failed"
            else:
                res_stats["leaf_categories"] = "PASSED"
            logger.info(f"leaf_categories: {res_stats['leaf_categories']}")
        except Exception as e:
            res_stats["leaf_categories"] = "ERROR"
            logger.error(f"Error in leaf_categories: {e}")

        try:
            logger.info('Checking product_ids...')
            ids_fetcher = IdsFetcher(proxy_manager=proxy_manager, token_manager=token_manager)
            p_ids, _ = ids_fetcher.fetch_product_ids_by_categories([leaf_categories[1]] if leaf_categories else 10, save_data=False)  # change to other default category ID if necessary
            if p_ids is None:
                res_stats["product_ids"] = "FAILED"
            else:
                res_stats["product_ids"] = "PASSED"
            logger.info(f"product_ids: {res_stats['product_ids']}")
        except Exception as e:
            res_stats["product_ids"] = "ERROR"
            logger.error(f"Error in product_ids: {e}")

        try:
            logger.info('Checking product_parser...')
            product_fetcher = ProductFetcher(proxy_manager=proxy_manager, token_manager=token_manager)
            # products, failed, status = product_parser.fetch_products([p_ids[0]] if p_ids else [1106551], save_data=False)  # change to other default product ID if necessary
            status, _ = product_fetcher.run([p_ids[0]] if p_ids else [1106551], save_data=False, send_data=False)
            if status != 0:
                res_stats["product_parser"] = "FAILED"
            else:
                res_stats["product_parser"] = "PASSED"
            logger.info(f"product_parser: {res_stats['product_parser']}; return status: {status}")
        except Exception as e:
            res_stats["product_parser"] = "ERROR"
            logger.error(f"Error in product_parser: {e}")

    except Exception as e:
        logger.error(f"System check: {e}")
    finally:
        if proxy_manager is not None:
            proxy_manager.shutdown_scheduler()

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
    if val:
        broker_host = val
    try:
        results = run_system_check(broker_host)
        # Determine exit code based on results
        if all(status == "PASSED" for status in results.values()):
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->system_check: {e}")
        sys.exit(1)
