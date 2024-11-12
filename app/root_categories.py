import http.client
import time
import json
import logging
import logging.config
import zlib
import brotli
import glob
import os
import sys
import configparser
from typing import List, Dict, Any
from fake_useragent import UserAgent
from save_and_load_data import save_to_file
from proxy_manager import ProxyManager
from send_data_to_db import send_message


current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

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
rc_dir = config.get('storage', 'root_categories_sub_dir')
lc_dir = config.get('storage', 'category_ids_sub_dir')
proxy_dir = config.get('storage', 'proxy_dir')

broker_host = config.get('broker', 'host')
broker_port = config.get('broker', 'port')

use_direct_connection = config.getboolean('root_categories', 'use_direct_connection')


def combine_products_into_tree(category_tree: Dict[str, Any], products_by_category: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combine fetched products into the category tree.

    Args:
        category_tree (Dict[str, Any]): The category tree data.
        products_by_category (Dict[str, Any]): Products categorized by their IDs.

    Returns:
        Dict[str, Any]: The combined category tree with products.
    """
    def traverse(node: Dict[str, Any]) -> None:
        node['products'] = products_by_category.get(node['id'], [])
        for child in node['children']:
            traverse(child)

    traverse(category_tree)
    return category_tree


def find_leaf_categories(category_tree: Dict[str, Any], save_data: bool = True, sort_result: bool = False) -> List[Dict[str, Any]]:
    """
    Recursively find all leaf categories in the category tree.

    Args:
        category_tree (Dict[str, Any]): The category tree data.

    Returns:
        List[Dict[str, Any]]: List of leaf categories.
    """

    logger.info("Retrieving leaf-categories...")
    leaf_categories = []

    def traverse(node: Dict[str, Any]) -> None:
        if 'children' in node:
            if not node['children']:
                leaf_categories.append(node)
            else:
                for child in node['children']:
                    traverse(child)
        else:
            logger.warning(f"No 'children' key found in node: {node.keys()}")

    try:
        if 'payload' in category_tree:
            for item in category_tree['payload']:
                traverse(item)
        else:
            logger.warning(
                "No 'payload' key found in the root of the category tree.")
    except Exception as e:
        logger.error(f"Failed to find leaf categories: {e}")

    if len(leaf_categories) > 0:
        if sort_result:
            leaf_categories = sorted(leaf_categories, key=lambda x: x['id'])
        logger.info(f"Extracted {len(leaf_categories)} categories from root-categories.")
        if save_data:
            try:
                save_to_file(leaf_categories, 'leaf_categories', lc_dir, add_date_time=True, separate_folder=False)
            except Exception as e:
                logger.error(f'Error in find_leaf_categories: {e}')
    return leaf_categories


def load_last_saved_root_categories(directory: str = f'{data_dir}/{rc_dir}') -> Dict[str, Any]:
    """
    Load the last saved root categories JSON file from the specified directory.

    Args:
        directory (str): The directory containing the JSON files.

    Returns:
        Dict[str, Any]: The root categories data.
    """
    try:
        list_of_files = glob.glob(os.path.join(
            directory, 'root_categories_*.json'))
        if not list_of_files:
            raise FileNotFoundError(
                "No root_categories files found in the directory.")

        latest_file = max(list_of_files, key=os.path.getctime)

        with open(latest_file, 'r', encoding='utf-8') as file:
            root_categories = json.load(file)

        logging.info(f'Loaded root-categories from {latest_file}')
        return root_categories

    except Exception as e:
        logging.error(f'Failed to load the last saved root-categories: {e}')
        return None


def find_title_by_id(data, target_id):
    """
    Recursively searches for a 'title' associated with a given 'id' in a nested JSON-like structure.

    Parameters:
    - data (dict or list): The JSON-like structure to search.
    - target_id (int): The ID to find the title for.

    Returns:
    - str: The title associated with the given ID, or None if not found.
    """
    if isinstance(data, dict):
        if data.get('id') == target_id:
            return data.get('title')

        if 'children' in data:
            for child in data['children']:
                result = find_title_by_id(child, target_id)
                if result:
                    return result

    elif isinstance(data, list):
        for item in data:
            result = find_title_by_id(item, target_id)
            if result:
                return result

    return None


def add_title_uz(rc1, rc2):
    """
    Adds a 'titleUz' key to each item in rc1 with the 'title' from rc2 that has a matching 'id'.
    Ensures 'titleUz' appears immediately after 'title' in each dictionary. If no match is found
    in rc2, assigns 'N/A' to 'titleUz'.

    Parameters:
    - rc1 (dict or list): The target JSON-like structure to add 'titleUz' keys.
    - rc2 (dict or list): The source structure from which to retrieve titles by ID.
    """
    if isinstance(rc1, dict):
        if 'title' in rc1:
            title_uz = find_title_by_id(rc2, rc1.get('id')) or "N/A"

            reordered_rc1 = {}
            for key, value in rc1.items():
                reordered_rc1[key] = value
                if key == 'title':
                    reordered_rc1['titleUz'] = title_uz
            rc1.clear()
            rc1.update(reordered_rc1)

        if 'children' in rc1:
            for child in rc1['children']:
                add_title_uz(child, rc2)

    elif isinstance(rc1, list):
        for item in rc1:
            add_title_uz(item, rc2)


def get_root_categories(request_retries: int = 8,
                        backoff_factor: int = 1,
                        root_categories_req_url: str = "https://api.uzum.uz/api/main/root-categories?eco=false",
                        main_url: str = "https://uzum.uz/",
                        accept_lang: List[str] = ['ru-RU', 'uz-UZ'],
                        use_direct_connection: bool = True,
                        load_most_recent_if_failed: bool = True,
                        send_to_broker: bool = True,
                        save_data: bool = True) -> Dict[str, Any]:
    """
    Fetch root categories from the API, with retries and backoff on failure.

    Args:
        request_retries (int, optional): Number of retries for the request.
        backoff_factor (int, optional): Backoff factor for retries.

    Returns:
        Dict[str, Any]: The root categories data.
    """
    ua = UserAgent()
    host = root_categories_req_url.split('//')[1].split('/')[0]
    endpoint = "/api" + root_categories_req_url.split('api')[-1]
    headers = {
        'authority': f'{host}',
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': f'{accept_lang[0]}',
        'Authorization': 'Bearer ',  # Include the actual token if needed
        'User-Agent': ua.random if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    root_categories = None
    request_attempts = 0
    if use_direct_connection:
        proxy_manager = None
    else:
        proxy_manager = ProxyManager.from_json_file(proxy_dir)

    def decompress_http_response(response_data: bytes, encoding: str) -> bytes:
        """
        Decompress the given HTTP response data based on its encoding.

        Args:
            response_data (bytes): The compressed response data.
            encoding (str): The encoding method.

        Returns:
            bytes: The decompressed data.
        """
        if encoding == 'gzip':
            return zlib.decompress(response_data, zlib.MAX_WBITS | 16)
        elif encoding == 'deflate':
            try:
                return zlib.decompress(response_data)
            except zlib.error:
                return zlib.decompress(response_data, -zlib.MAX_WBITS)
        elif encoding == 'br':
            return brotli.decompress(response_data)
        else:
            return response_data

    def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
        logger.info(f"Server rejected. Attempt number {request_attempts}")
        wait_time = backoff_factor * (2 ** request_attempts)
        logger.info(f"Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    while request_attempts <= request_retries:
        try:
            if use_direct_connection:
                logger.info("Establishing a direct connection")
                conn = http.client.HTTPSConnection(host)
            else:
                logger.debug(f"Picking a proxy and establishing a connection")
                conn, _ = proxy_manager.make_connection(host)
                if conn is None:
                    logger.warning(f"No proxy connection! Establishing direct connection to {host}")
                    conn = http.client.HTTPSConnection(host)
            for lang in range(len(accept_lang)):
                headers['Accept-Language'] = accept_lang[lang]
                conn.request("GET", endpoint, headers=headers)
                response = conn.getresponse()
                rc = None
                if response.status == 200:
                    response_data = response.read()
                    content_encoding = response.getheader('Content-Encoding')

                    if content_encoding:
                        response_data = decompress_http_response(response_data, content_encoding)

                    decoded_data = response_data.decode('utf-8')
                    if not decoded_data:
                        raise ValueError("Empty response data")
                    rc = json.loads(decoded_data)
                    logger.info(f'Collected root-categories from {main_url}:{headers['Accept-Language']}')
                else:
                    raise ValueError(f"HTTP error occurred while fetching root-categories: Status code {response.status}")
                if rc:
                    if lang:
                        try:
                            print("before")
                            add_title_uz(root_categories['payload'], rc['payload'])
                            print('after')
                            # root_categories = rc
                        except Exception as e:
                            logger.error(f'Error while merging titles: {e}')
                    else:
                        root_categories = rc
            break
        except Exception as e:
            logger.error(e)
            request_attempts += 1
            if request_attempts > request_retries:
                logger.error('Exceeded max number of retries!')
                break
            wait_with_backoff(request_attempts, backoff_factor)
            if ua is not None:
                headers['User-Agent'] = f'{ua.random}'
        finally:
            if proxy_manager:
                proxy_manager.shutdown_scheduler()
            if conn is not None:
                conn.close()

    if root_categories is None:
        logger.warning(f'No root-categories collected from {main_url}')
        if load_most_recent_if_failed:
            logger.info('Loading the most recent root-categories...')
            root_categories = load_last_saved_root_categories()
    else:
        if send_to_broker:
            try:
                send_message(root_categories, host=broker_host, port=broker_port, queue_name='uzum_categories')
            except Exception as e:
                logger.error(f'Failed sending message to RabbitMQ broker: {e}')
        if save_data:
            try:
                save_to_file(root_categories, rc_dir, rc_dir, add_date_time=True, separate_folder=False)
            except Exception as e:
                logger.error(f'Error in get_root_categories: {e}')
    return root_categories


if __name__ == "__main__":
    try:
        rc = get_root_categories(use_direct_connection=use_direct_connection)
        lc = find_leaf_categories(rc)

    except Exception as e:
        logger.error(f"In {sys.argv[0]}->main: {e}")
