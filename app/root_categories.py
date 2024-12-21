# import argparse
# import uuid
import copy
import configparser
import brotli
import zlib
import logging.config
import json
import time
import http.client
import glob
import os
import sys
from typing import List, Dict, Any, Tuple, Optional
from fake_useragent import UserAgent
from save_and_load_data import save_to_file, load_last_saved_json, load_json
from proxy_manager import ProxyManager
from send_data_to_db import send_message
from token_manager import TokenManager

# Define current directory and configuration paths
current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

# Configure logging
try:
    logging.config.fileConfig(logging_config_path)
    logger = logging.getLogger('root_categories')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

# Read configuration
config = configparser.ConfigParser()
config.read(config_path)

# Initialize directories and broker settings from config
data_dir = os.path.join(current_dir, config.get('storage', 'data_directory'))
graphql_dir = os.path.join(current_dir, config.get('storage', 'graphql_dir'))
rc_dir = config.get('storage', 'root_categories_sub_dir')
lc_dir = config.get('storage', 'category_ids_sub_dir')
ct_dir = config.get('storage', 'category_tree_dir')
proxy_dir = config.get('storage', 'proxy_dir')

main_url = config.get('urls', 'main_url')

broker_host = config.get('broker', 'host')
broker_port = config.getint('broker', 'port')

use_direct_connection = config.getboolean('root_categories', 'use_direct_connection')


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
    """
    Wait for a certain period based on the backoff factor and the number of request attempts.

    Args:
        request_attempts (int): The current number of request attempts.
        backoff_factor (float): The backoff factor to calculate wait time.
    """
    logger.info(f"Server rejected. Attempt number {request_attempts}")
    wait_time = backoff_factor * (2 ** request_attempts)
    logger.info(f"Retrying in {wait_time} seconds...")
    time.sleep(wait_time)


def get_response(headers: Dict[str, str], proxy_manager: Optional[ProxyManager] = None) -> Optional[http.client.HTTPResponse]:
    """
    Make an HTTP request and return the response.

    Args:
        headers (Dict[str, str]): HTTP headers to include in the request.
        proxy_manager (Optional[ProxyManager], optional): Proxy manager to handle proxy connections. Defaults to None.

    Returns:
        Optional[http.client.HTTPResponse]: The HTTP response if successful, else None.
    """
    # Placeholder implementation. Implement according to specific requirements.
    pass


def initialize_managers(proxy_manager: ProxyManager = None, token_manager: TokenManager = None, use_direct_connection: bool = use_direct_connection, **kwargs) -> bool:
    proxy_close = False
    if not proxy_manager and not use_direct_connection:
        logger.debug("Initializing ProxyManager in root_categories")
        proxy_manager = ProxyManager.from_json_file(proxy_dir)
        proxy_close = True
    if not token_manager:
        logger.debug("Initializing TokenManager in root_categories")
        token_manager = TokenManager(
            proxy_manager=proxy_manager,
            url=main_url,
            max_retries=kwargs.get('token_retries', 5),
            save_token=kwargs.get('save_token', False),
            save_cookies=False
        )
        auth_token = token_manager.get_token_instance()
        if auth_token is None:
            raise FileNotFoundError("Failed to get authorization token.")
    return proxy_manager, token_manager, proxy_close


def get_category_tree(
        proxy_manager: Optional[ProxyManager] = None,
        token_manager: Optional[TokenManager] = None,
        request_retries: int = 8,
        backoff_factor: int = 1,
        graphql_req_url: str = "https://graphql.uzum.uz/",
        main_url: str = "https://uzum.uz/",
        use_direct_connection: bool = False,
        load_most_recent_if_failed: bool = True,
        save_data: bool = True,
        **kwargs) -> Dict[str, Any]:
    """
    Fetch the category tree from the GraphQL API with retries and backoff on failure.

    Args:
        request_retries (int, optional): Number of retries for the request. Defaults to 8.
        backoff_factor (int, optional): Backoff factor for retries. Defaults to 1.
        graphql_req_url (str, optional): GraphQL API URL. Defaults to "https://graphql.uzum.uz/".
        main_url (str, optional): Main URL of the platform. Defaults to "https://uzum.uz/".
        use_direct_connection (bool, optional): Whether to use direct connection without proxies. Defaults to True.
        proxy_manager (Optional[ProxyManager], optional): Proxy manager instance. Defaults to None.
        load_most_recent_if_failed (bool, optional): Whether to load the most recent saved category tree if fetching fails. Defaults to True.
        save_data (bool, optional): Whether to save the fetched category tree to a file. Defaults to True.

    Returns:
        Dict[str, Any]: The fetched category tree data.
    """
    proxy_manager, token_manager, proxy_close = initialize_managers(proxy_manager, token_manager, use_direct_connection)
    auth_token = token_manager.get_token()
    ua = UserAgent()
    host = graphql_req_url.split('//')[1].split('/')[0]
    endpoint = "/"
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'ru-RU',
        'apollographql-client-name': 'web-customers',
        'apollographql-client-version': '1.25.2',
        'Authorization': f'Bearer {auth_token}',
        'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=dcdef1759da34ae6894f8629c5d59343',
        'Content-Type': 'application/json',
        'Origin': f'{main_url}',
        'Priority': 'u=1, i',
        'Referer': f'{main_url}',
        'sec-fetch-site': 'same-site',
        'sentry-trace': 'dcdef1759da34ae6894f8629c5d59343-a55aaf4639abcfa1',
        'User-Agent': ua.random,
        'x-context': 'null',
        'x-iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7'
    }

    payload_json = load_json(f"{graphql_dir}/{ct_dir}.json")

    category_tree = None
    request_attempts = 0

    # if use_direct_connection:
    #     proxy_manager = None
    # else:
    #     if proxy_manager is None:
    #         proxy_manager = ProxyManager.from_json_file(proxy_dir)
    #         proxy_close = True

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

            conn.request("POST", endpoint, json.dumps(payload_json), headers=headers)
            response = conn.getresponse()
            if response.status == 200:
                response_data = response.read()
                content_encoding = response.getheader('Content-Encoding')

                if content_encoding:
                    response_data = decompress_http_response(response_data, content_encoding)

                decoded_data = response_data.decode('utf-8')
                if not decoded_data:
                    raise ValueError("Empty response data")
                category_tree = json.loads(decoded_data)
                logger.info(f"Collected category tree from {main_url} with Accept-Language: {headers['Accept-Language']}")
            else:
                raise ValueError(f"HTTP error occurred while fetching category tree from GraphQL: Status code {response.status}")
            break
        except Exception as e:
            logger.error(f"Attempt {request_attempts + 1} failed: {e}")
            request_attempts += 1
            if request_attempts > request_retries:
                logger.error('Exceeded max number of retries!')
                break
            wait_with_backoff(request_attempts, backoff_factor)
            if ua is not None:
                headers['User-Agent'] = ua.random
        finally:
            if 'conn' in locals() and conn is not None:
                conn.close()

    if proxy_manager and proxy_close:
        proxy_manager.shutdown_scheduler()

    if category_tree is None:
        logger.warning(f"No category tree collected from {main_url}")
        if load_most_recent_if_failed:
            logger.info('Loading most recent category tree...')
            category_tree = load_last_saved_json(f"{data_dir}/{ct_dir}", f"{ct_dir}.json")
    if save_data and category_tree:
        try:
            save_to_file(category_tree, ct_dir, ct_dir, add_date_time=False, separate_folder=False)
        except Exception as e:
            logger.error(f'Error in get_category_tree: {e}')
    return category_tree


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
        node['products'] = products_by_category.get(str(node['id']), [])
        for child in node.get('children', []):
            traverse(child)

    traverse(category_tree)
    return category_tree


def find_children_of_leaf(category_tree: Dict[str, Any], leaf_node: int) -> List[Dict[str, Any]]:
    """
    Find all child categories of a given leaf node in the category tree.

    Args:
        category_tree (Dict[str, Any]): The category tree data.
        leaf_node (int): The ID of the leaf node.

    Returns:
        List[Dict[str, Any]]: A list of child categories.
    """
    data = category_tree.get("data", {}).get("makeSearch", {}).get("categoryTree", [])
    res = []
    for category in data:
        if "category" in category:
            category_i = category.get("category", {})
            parent = category_i.get("parent")
            if not parent or not isinstance(parent, dict):
                continue
            else:
                if parent.get("id") == leaf_node:
                    child = {
                        "id": category_i.get("id"),
                        "productAmount": category.get("total", 0),
                        "adult": category_i.get("adult", False),
                        "eco": False,
                        "iconLink": category_i.get("icon"),
                        "title": category_i.get("title_ru"),
                        "titleUz": category_i.get("title_uz"),
                        "seoMetaTag": category_i.get("seo", {}).get("metaTag"),
                        "seoHeader": category_i.get("seo", {}).get("header"),
                        "children": [],
                        "path": [category_i.get("id")]
                    }
                    res.append(child)
    return res


def find_leaf_categories(
        category_tree: Dict[str, Any],
        category_tree_gql: Optional[Dict[str, Any]] = None,
        save_data: bool = True,
        sort_result: bool = False
) -> List[Dict[str, Any]]:
    """
    Recursively find all leaf categories in the category tree.

    Args:
        category_tree (Dict[str, Any]): The category tree data.
        category_tree_gql (Optional[Dict[str, Any]], optional): Additional category tree data from GraphQL. Defaults to None.
        save_data (bool, optional): Whether to save the leaf categories to a file. Defaults to True.
        sort_result (bool, optional): Whether to sort the resulting leaf categories. Defaults to False.

    Returns:
        List[Dict[str, Any]]: List of leaf categories.
    """
    logger.info("Retrieving leaf categories...")
    leaf_categories = []

    def traverse(node: Dict[str, Any]) -> None:
        if 'children' in node:
            if not node['children']:
                new_children = None
                if category_tree_gql is not None:
                    new_children = find_children_of_leaf(category_tree_gql, node["id"])
                if new_children:
                    for child in new_children:
                        child["path"] = node["path"] + child["path"]
                        leaf_categories.append(child)
                    node['children'] = new_children
                else:
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
            logger.warning("No 'payload' key found in the root of the category tree.")
    except Exception as e:
        logger.error(f"Failed to find leaf categories: {e}")

    if leaf_categories:
        if sort_result:
            leaf_categories = sorted(leaf_categories, key=lambda x: x['id'])
        logger.info(f"Extracted {len(leaf_categories)} leaf categories from root-categories.")
        if save_data:
            try:
                save_to_file(leaf_categories, 'leaf_categories', lc_dir, add_date_time=True, separate_folder=False)
            except Exception as e:
                logger.error(f'Error in find_leaf_categories: {e}')
    return leaf_categories


def load_last_saved_root_categories(directory: str = f'{data_dir}/{rc_dir}') -> Optional[Dict[str, Any]]:
    """
    Load the last saved root categories JSON file from the specified directory.

    Args:
        directory (str, optional): The directory containing the JSON files. Defaults to f'{data_dir}/{rc_dir}'.

    Returns:
        Optional[Dict[str, Any]]: The root categories data if successful, else None.
    """
    try:
        list_of_files = glob.glob(os.path.join(directory, 'root_categories_*.json'))
        if not list_of_files:
            raise FileNotFoundError("No root_categories files found in the directory.")

        latest_file = max(list_of_files, key=os.path.getctime)

        with open(latest_file, 'r', encoding='utf-8') as file:
            root_categories = json.load(file)

        logger.info(f'Loaded root categories from {latest_file}')
        return root_categories

    except Exception as e:
        logger.error(f'Failed to load the last saved root categories: {e}')
        return None


def find_title_by_id(data: Any, target_id: int) -> Optional[str]:
    """
    Recursively search for a 'title' associated with a given 'id' in a nested JSON-like structure.

    Args:
        data (Any): The JSON-like structure to search.
        target_id (int): The ID to find the title for.

    Returns:
        Optional[str]: The title associated with the given ID, or None if not found.
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


def add_title_uz(rc1: Any, rc2: Any) -> None:
    """
    Add a 'titleUz' key to each item in rc1 with the 'title' from rc2 that has a matching 'id'.
    Ensures 'titleUz' appears immediately after 'title' in each dictionary. If no match is found
    in rc2, assigns 'N/A' to 'titleUz'.

    Args:
        rc1 (Any): The target JSON-like structure to add 'titleUz' keys.
        rc2 (Any): The source structure from which to retrieve titles by ID.
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


def get_root_categories(
        proxy_manager: Optional[ProxyManager] = None,
        request_retries: int = 8,
        backoff_factor: int = 1,
        root_categories_req_url: str = "https://api.uzum.uz/api/main/root-categories?eco=false",
        main_url: str = "https://uzum.uz/",
        accept_lang: List[str] = ['ru-RU', 'uz-UZ'],
        use_direct_connection: bool = False,
        load_most_recent_if_failed: bool = True,
        send_to_broker: bool = False,
        save_data: bool = True
) -> Dict[str, Any]:
    """
    Fetch root categories from the API, with retries and backoff on failure.

    Args:
        request_retries (int, optional): Number of retries for the request. Defaults to 8.
        backoff_factor (int, optional): Backoff factor for retries. Defaults to 1.
        root_categories_req_url (str, optional): Root categories API URL. Defaults to "https://api.uzum.uz/api/main/root-categories?eco=false".
        main_url (str, optional): Main URL of the platform. Defaults to "https://uzum.uz/".
        accept_lang (List[str], optional): List of accepted languages for the request. Defaults to ['ru-RU', 'uz-UZ'].
        use_direct_connection (bool, optional): Whether to use direct connection without proxies. Defaults to True.
        proxy_manager (Optional[ProxyManager], optional): Proxy manager instance. Defaults to None.
        load_most_recent_if_failed (bool, optional): Whether to load the most recent saved root categories if fetching fails. Defaults to True.
        send_to_broker (bool, optional): Whether to send the fetched data to a message broker. Defaults to False.
        save_data (bool, optional): Whether to save the fetched data to a file. Defaults to True.

    Returns:
        Dict[str, Any]: The fetched root categories data.
    """
    ua = UserAgent()
    host = root_categories_req_url.split('//')[1].split('/')[0]
    endpoint = "/api" + root_categories_req_url.split('api')[-1]
    headers = {
        'authority': host,
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': accept_lang[0],
        'Authorization': 'Bearer ',  # Include the actual token if needed
        'User-Agent': ua.random if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    root_categories = None
    request_attempts = 0
    proxy_close = False
    if use_direct_connection:
        proxy_manager = None
    else:
        if proxy_manager is None:
            proxy_manager = ProxyManager.from_json_file(proxy_dir)
            proxy_close = True

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
                    logger.info(f"Collected root categories from {main_url} with Accept-Language: {headers['Accept-Language']}")
                else:
                    raise ValueError(f"HTTP error occurred while fetching root categories: Status code {response.status}")
                if rc:
                    if lang:
                        try:
                            add_title_uz(root_categories['payload'], rc['payload'])
                        except Exception as e:
                            logger.error(f'Error while merging titles: {e}')
                    else:
                        root_categories = rc
            break
        except Exception as e:
            logger.error(f"Attempt {request_attempts + 1} failed: {e}")
            request_attempts += 1
            if request_attempts > request_retries:
                logger.error('Exceeded max number of retries!')
                break
            wait_with_backoff(request_attempts, backoff_factor)
            if ua is not None:
                headers['User-Agent'] = ua.random
        finally:
            if 'conn' in locals() and conn is not None:
                conn.close()

    if proxy_manager and proxy_close:
        proxy_manager.shutdown_scheduler()

    if root_categories is None:
        logger.warning(f"No root categories collected from {main_url}")
        if load_most_recent_if_failed:
            logger.info('Loading the most recent root categories...')
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


def get_all_root_categories(
        proxy_manager: Optional[ProxyManager] = None,
        token_manager: Optional[TokenManager] = None,
        request_retries: int = 8,
        backoff_factor: int = 1,
        root_categories_req_url: str = "https://api.uzum.uz/api/main/root-categories?eco=false",
        graphql_req_url: str = "https://graphql.uzum.uz/",
        main_url: str = "https://uzum.uz/",
        accept_lang: List[str] = ['ru-RU', 'uz-UZ'],
        use_direct_connection: bool = use_direct_connection,
        load_most_recent_if_failed: bool = True,
        send_to_broker: bool = True,
        save_data: bool = True
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Retrieve all root categories and their leaf categories.

    Args:
        request_retries (int, optional): Number of retries for requests. Defaults to 8.
        backoff_factor (int, optional): Backoff factor for retries. Defaults to 1.
        root_categories_req_url (str, optional): Root categories API URL. Defaults to "https://api.uzum.uz/api/main/root-categories?eco=false".
        graphql_req_url (str, optional): GraphQL API URL. Defaults to "https://graphql.uzum.uz/".
        main_url (str, optional): Main URL of the platform. Defaults to "https://uzum.uz/".
        accept_lang (List[str], optional): List of accepted languages for requests. Defaults to ['ru-RU', 'uz-UZ'].
        use_direct_connection (bool, optional): Whether to use direct connection without proxies. Defaults to True.
        proxy_manager (Optional[ProxyManager], optional): Proxy manager instance. Defaults to None.
        load_most_recent_if_failed (bool, optional): Whether to load the most recent saved data if fetching fails. Defaults to True.
        send_to_broker (bool, optional): Whether to send the fetched data to a message broker. Defaults to True.
        save_data (bool, optional): Whether to save the fetched data to files. Defaults to True.

    Returns:
        Tuple[Dict[str, Any], List[Dict[str, Any]]]: A tuple containing the root categories and the list of leaf categories.
    """
    proxy_manager, token_manager, proxy_close = initialize_managers(proxy_manager, token_manager, use_direct_connection)
    try:
        ct = get_category_tree(
            proxy_manager=proxy_manager,
            token_manager=token_manager,
            request_retries=request_retries,
            backoff_factor=backoff_factor,
            graphql_req_url=graphql_req_url,
            main_url=main_url,
            accept_lang=accept_lang,
            use_direct_connection=use_direct_connection,
            load_most_recent_if_failed=load_most_recent_if_failed,
            save_data=save_data
        )
        rc = get_root_categories(
            proxy_manager=proxy_manager,
            backoff_factor=backoff_factor,
            root_categories_req_url=root_categories_req_url,
            main_url=main_url,
            accept_lang=accept_lang,
            use_direct_connection=use_direct_connection,
            load_most_recent_if_failed=load_most_recent_if_failed,
            send_to_broker=False,
            save_data=save_data
        )

        rc_s = copy.deepcopy(rc)

        find_leaf_categories(rc, ct)

        if send_to_broker:
            try:
                send_message(rc, host=broker_host, port=broker_port, queue_name='uzum_categories')
            except Exception as e:
                logger.error(f'Failed sending message to RabbitMQ broker: {e}')

        if save_data:
            try:
                save_to_file(rc, f"{rc_dir}_extnd", rc_dir, add_date_time=True, separate_folder=False)
            except Exception as e:
                logger.error(f'Error in get_all_root_categories: {e}')
    except Exception as e:
        logger.error(f"Error in get_all_root_categories: {e}")
    finally:
        if proxy_close and proxy_manager is not None:
            proxy_manager.shutdown_scheduler()
    return rc, rc_s


if __name__ == "__main__":
    try:
        get_all_root_categories()
        # Additional processing can be added here if needed
    except Exception as e:
        logger.error(f"In {sys.argv[0]}->main: {e}")
