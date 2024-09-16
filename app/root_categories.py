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
from typing import List, Dict, Any
from fake_useragent import UserAgent
import configparser
from save_and_load_data import save_to_file


# Configure logging
try:
    logging.config.fileConfig('configs/logging.conf')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
finally:
    logger = logging.getLogger()

config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
rc_dir = config.get('storage', 'root_categories_sub_dir')
lc_dir = config.get('storage', 'category_ids_sub_dir')


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


def find_leaf_categories(category_tree: Dict[str, Any], save_data: bool = True, sort_result: bool = True) -> List[Dict[str, Any]]:
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


def get_root_categories(request_retries: int = 8,
                        backoff_factor: int = 1,
                        root_categories_req_url: str = "https://api.uzum.uz/api/main/root-categories?eco=false",
                        main_url: str = "https://uzum.uz/ru",
                        load_most_recent_if_failed: bool = True,
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
        'Accept-Language': 'ru-RU',
        'Authorization': 'Bearer ',  # Include the actual token if needed
        'User-Agent': ua.random if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    root_categories = None
    request_attempts = 0

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
            conn = http.client.HTTPSConnection(host)
            conn.request("GET", endpoint, headers=headers)
            response = conn.getresponse()

            if response.status == 200:
                response_data = response.read()
                content_encoding = response.getheader('Content-Encoding')

                if content_encoding:
                    response_data = decompress_http_response(response_data, content_encoding)

                decoded_data = response_data.decode('utf-8')
                if not decoded_data:
                    raise ValueError("Empty response data")
                root_categories = json.loads(decoded_data)
                if save_data:
                    try:
                        save_to_file(root_categories, rc_dir, rc_dir, add_date_time=True, separate_folder=False)
                    except Exception as e:
                        logger.error(f'Error in get_root_categories: {e}')

                logger.info(f'Collected root-categories from {main_url}')
                break  # Exit the loop if the request is successful
            else:
                raise ValueError(
                    f"HTTP error occurred while fetching root-categories: Status code {response.status}")

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
            conn.close()

    if root_categories is None:
        logger.warning(
            f'No root-categories collected from {main_url}')
        if load_most_recent_if_failed:
            logger.info('Loading the most recent root-categories...')
            root_categories = load_last_saved_root_categories()
    return root_categories


if __name__ == "__main__":
    try:
        rc = get_root_categories()
        lc = find_leaf_categories(rc)

    except Exception as e:
        logger.error(f"In {sys.argv[0]}->main: {e}")
