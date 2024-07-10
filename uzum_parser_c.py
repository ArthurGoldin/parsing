import http.client
import time
import json
from datetime import datetime
import os
import glob
import csv
import pandas as pd
import logging
import zlib
import brotli
from typing import List, Tuple, Dict, Any

from token_manager import TokenManager
import graphql_query_generator

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

    if add_date_time:
        file_name = f'{file_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    with open(f'{dir_path}/{file_name}.csv', 'w', newline='') as write_file:
        writer = csv.writer(write_file)
        writer.writerow(file)
        logger.info(f"{file_name.split('_')[0]} saved to a .csv file")


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


def get_root_categories(request_retries: int = 8, backoff_factor: int = 1) -> Dict[str, Any]:
    """
    Fetch root categories from the API, with retries and backoff on failure.

    Args:
        request_retries (int, optional): Number of retries for the request.
        backoff_factor (int, optional): Backoff factor for retries.

    Returns:
        Dict[str, Any]: The root categories data.
    """
    host = root_categories_req_url.split('//')[1].split('/')[0]
    endpoint = "/api" + root_categories_req_url.split('api')[-1]
    headers = {
        'authority': 'api.uzum.uz',
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'ru-RU',
        'Authorization': 'Bearer ',  # Include the actual token if needed
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    root_categories = None
    request_attempts = 0

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
                    response_data = decompress_http_response(
                        response_data, content_encoding)

                decoded_data = response_data.decode('utf-8')
                if not decoded_data:
                    raise ValueError("Empty response data")
                root_categories = json.loads(decoded_data)
                with open(f"{data_dir}/root_categories/root_categories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", 'w', encoding='utf-8') as file:
                    json.dump(root_categories, file,
                              ensure_ascii=False, indent=4)
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
        finally:
            conn.close()

    return root_categories


def get_ids_from_json(json_data: Dict[str, Any]) -> List[int]:
    """
    Extract product IDs from the given JSON data.

    Args:
        json_data (Dict[str, Any]): The JSON data.

    Returns:
        List[int]: List of product IDs.
    """
    items = json_data.get("data", {}).get("makeSearch", {}).get("items", [])
    product_ids = [item.get("catalogCard", {}).get(
        "productId") for item in items if "catalogCard" in item and "productId" in item["catalogCard"]]
    return product_ids


def get_product_ids_by_category(category_id: int, amount: int, page_limit: int = 100, request_retries: int = 8, backoff_factor: int = 1, save_category_ids: bool = False) -> Tuple[List[int], int]:
    """
    Fetch product IDs by category with pagination and retries.

    Args:
        category_id (int): The category ID.
        amount (int): The total amount of products to fetch.
        page_limit (int, optional): The limit of products per page.
        request_retries (int, optional): Number of retries for the request.
        backoff_factor (int, optional): Backoff factor for retries.
        save_category_ids (bool, optional): Whether to save the fetched IDs to a CSV file.

    Returns:
        Tuple[List[int], int]: A tuple containing the list of product IDs and the status code.
    """
    global auth_token
    global token_manager
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'ru-RU',
        'apollographql-client-name': 'web-customers',
        'apollographql-client-version': '1.26.4',
        'Authorization': f'Bearer {auth_token}',
        'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.26.3,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=23a72fc6b9fd48769e62a090a50b9a90',
        'Content-Type': 'application/json',
        'Origin': f"{main_url}",
        'Priority': 'u=1, i',
        'Referer': f"{main_url}/",
        'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-site',
        'sentry-trace': 'dcdef1759da34ae6894f8629c5d59343-a55aaf4639abcfa1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'x-context': 'null',
        'x-iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7',
        'Connection': 'keep-alive'
    }
    host = graphql_url.split('//')[1].split('/')[0]
    endpoint = '/'

    payload_json = graphql_query_generator.generate_query()
    query_sort_types = ['BY_RELEVANCE_DESC', 'BY_RELEVANCE_ASC',
                        'BY_RATING_DESC', 'BY_RATING_ASC', 'BY_ORDERS_NUMBER_DESC', 'BY_ORDERS_NUMBER_ASC', 'BY_DATE_ADDED_ASC', 'BY_DATE_ADDED_DESC', 'BY_PRICE_ASC', 'BY_PRICE_DESC']
    query_sort_ind = 0
    items_offset = 0
    data_list = []
    prev_data = []
    request_attempts = 0
    done = False
    status = None

    def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
        logger.info(f"Server rejected. Attempt number {request_attempts}")
        wait_time = backoff_factor * (2 ** request_attempts)
        logger.info(f"Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    conn = http.client.HTTPSConnection(host)

    while not done and request_attempts <= request_retries:
        graphql_query_generator.set_query_variables(
            data=payload_json, category_id=category_id, offset=items_offset, limit=page_limit, sort=query_sort_types[query_sort_ind])

        try:
            conn.request("POST", endpoint, json.dumps(
                payload_json), headers=headers)
            response = conn.getresponse()
            status = response.status
            if response.status == 200:
                response_data = response.read()
                content_encoding = response.getheader('Content-Encoding')

                if content_encoding:
                    response_data = decompress_http_response(
                        response_data, content_encoding)
                decoded_data = response_data.decode('utf-8')

                if not decoded_data:
                    raise ValueError("Empty response data from graphql query")

                json_data = json.loads(decoded_data)

                # Check for errors in the response
                if 'errors' in json_data:
                    error_messages = [
                        error.get('message', 'Unknown error') for error in json_data['errors']]
                    error_429 = False
                    for error_message in error_messages:
                        logger.error(f'GraphQL Error: {error_message}')
                        if '429' in error_message:
                            error_429 = True

                    if error_429:
                        status = 429
                        wait_with_backoff(request_attempts, backoff_factor)
                        if request_attempts == 0:
                            conn.close()
                            new_token = token_manager.get_token_instance()
                            if new_token is not None:
                                auth_token = new_token
                                headers['Authorization'] = f'Bearer {
                                    auth_token}'
                            conn = http.client.HTTPSConnection(host)
                        request_attempts += 1
                        continue

                data = get_ids_from_json(json_data)
                if len(data) > 0:
                    data_list.extend(data)
                else:
                    done = True
                    amount = json_data.get("data", {}).get(
                        "makeSearch", {}).get("total")

                logger.info(f'Collected {len(data)} of total {
                            len(data_list)} collected items in category {category_id}')

                items_offset += min(page_limit, amount - len(data_list))
                if (len(data_list) >= amount) or (data == prev_data):
                    done = True

                # If reached the offset limit, try other types of query sorting to extract maximum data
                if items_offset >= 10000:
                    if query_sort_ind < len(query_sort_types) - 1:
                        items_offset = 0
                        query_sort_ind += 1
                        logger.info(f"Reached the API offset limit of 10,000. Switching to sort type {
                                    query_sort_types[query_sort_ind]}")
                        # add 10000 to prevent stopping (the amount is now irrelevant)
                        amount += 10000
                    else:
                        done = True

                prev_data = data
                request_attempts = 0

            elif response.status == 401:  # authorization failed
                logger.info(
                    f"{response.status}: Authorization failed during the GraphQL query; retrieving a new token...")
                conn.close()
                wait_with_backoff(request_attempts, backoff_factor)
                auth_token = token_manager.get_token_instance()
                logger.info(auth_token)
                headers['Authorization'] = f'Bearer {auth_token}'
                request_attempts += 1
                conn = http.client.HTTPSConnection(host)
            elif response.status == 429:
                # Server blocking due to multiple requests
                logger.info(
                    "429: Blocked by a server due to too many requests.")
                wait_with_backoff(request_attempts, backoff_factor)
                request_attempts += 1
                continue
            else:
                raise ValueError(f"Bad response status on a GraphQL query: {
                                 response.status}")
        except Exception as e:
            logger.error(f'Failed to receive data from a GraphQl query: {e}')
            break

    conn.close()

    if len(data_list) != 0:
        logger.info(f"Finished retrieving category ids. Total collected {
                    len(data_list)} out of {amount} in GraphQL in category {category_id}")
        data_list = list(set(data_list))
        logger.info(f"Total unique ids: {len(data_list)} in category {
                    category_id}, return status: {status}")
        if save_category_ids:
            save_csv(data_list, f'category_{
                     category_id}_pr_ids', 'products_by_category')
    else:
        logger.warning(f"No items collected from category {
                       category_id}, return status: {status}")

    return data_list, status


def load_last_saved_root_categories(directory: str) -> Dict[str, Any]:
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


def load_category_tree(file_path: str) -> Dict[str, Any]:
    """
    Load category tree from a JSON file.

    Args:
        file_path (str): Path to the JSON file.

    Returns:
        Dict[str, Any]: The category tree data.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def find_leaf_categories(category_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Recursively find all leaf categories in the category tree.

    Args:
        category_tree (Dict[str, Any]): The category tree data.

    Returns:
        List[Dict[str, Any]]: List of leaf categories.
    """
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
    return leaf_categories


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


def fetch_product_ids_by_categories(categories: List[Dict[str, Any]], save_fetched_data: bool = True) -> List[int]:
    """
    Fetch product IDs by categories and optionally save the fetched data.

    Args:
        categories (List[Dict[str, Any]]): List of categories to fetch product IDs from.
        save_fetched_data (bool, optional): Whether to save the fetched data to a CSV file.

    Returns:
        List[int]: List of fetched product IDs.
    """
    global token_manager
    token_manager = TokenManager(
        url=main_url,
        max_retries=4,
        save_token=False,
        save_cookies=False
    )
    global auth_token
    auth_token = token_manager.get_token_instance()

    if auth_token is not None:
        product_ids = []
        failed_categories = []
        for category in categories:
            category_ids, status = get_product_ids_by_category(
                category_id=category['id'], amount=category['productAmount'])
            if len(category_ids) > 0:
                product_ids.extend(category_ids)
            if status != 200:
                failed_categories.append(
                    {"id": category['id'], "productAmount": category['productAmount'], "status": status})
            break

        logger.info(f"Total {len(product_ids)} ids fetched.")
        product_ids = list(set(product_ids))
        logger.info(f"Total unique ids fetched: {len(product_ids)}")
        logger.info(f'Total number of failed categories: {
                    len(failed_categories)}')

        if save_fetched_data:
            if product_ids:
                save_csv(product_ids, 'product_ids', 'product_ids')

            if failed_categories:
                save_csv(failed_categories, 'failed_categories_ids',
                         'failed_categories')
                with open(f"{data_dir}/failed_categories_ids/root_categories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", 'w', encoding='utf-8') as file:
                    json.dump(failed_categories, file,
                              ensure_ascii=False, indent=4)

        return product_ids
    else:
        raise FileNotFoundError("Failed to get authorization token.")


def parse_product(json_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str] | str]:
    """
    Parse product information from the given JSON data.

    Args:
        json_data (Dict[str, Any]): The JSON data.

    Returns:
        Tuple[Dict[str, Any], Dict[str, str] | str]: The parsed product data and any error messages.
    """
    try:
        payload = json_data.get('payload', {}).get('data', {})

        if not payload:
            raise ValueError("Payload or data is missing in the JSON file.")

        result = {
            'id': payload.get('id', None),
            'title': payload.get('title', None),
            'category_id': payload.get('category', {}).get('id', None),
            'category_title': payload.get('category', {}).get('title', None),
            'rating': payload.get('rating', None),
            'reviewsAmount': payload.get('reviewsAmount', None),
            'ordersAmount': payload.get('ordersAmount', None),
            'totalAvailableAmount': payload.get('totalAvailableAmount', None),
            'skuList': [{
                'availableAmount': sku.get('availableAmount', None),
                'fullPrice': sku.get('fullPrice', None),
                'purchasePrice': sku.get('purchasePrice', None)
            } for sku in payload.get('skuList', [])],
            'seller_id': payload.get('seller', {}).get('id', None),
            'seller_title': payload.get('seller', {}).get('title', None),
            'seller_rating': payload.get('seller', {}).get('rating', None),
            'seller_reviews': payload.get('seller', {}).get('reviews', None),
            'seller_orders': payload.get('seller', {}).get('orders', None),
            'url': f'{main_url}/product/{payload.get("id", None)}',
        }

        # Check for null values and add error messages if any
        error_messages = {}
        for key, value in result.items():
            if value is None:
                error_messages[key] = f"{
                    key} is missing or null in the JSON file."

        if error_messages:
            return None, error_messages

        return result, None

    except Exception as e:
        return None, str(e)


def fetch_products(product_ids: List[int], request_retries: int = 8, backoff_factor: int = 1) -> Tuple[List[Dict[str, Any]], List[int]]:
    """
    Fetch product details for the given product IDs with retries and backoff on failure.

    Args:
        product_ids (List[int]): List of product IDs to fetch.
        request_retries (int, optional): Number of retries for the request.
        backoff_factor (int, optional): Backoff factor for retries.

    Returns:
        Tuple[List[Dict[str, Any]], List[int]]: A tuple containing the list of product details and the list of failed product IDs.
    """
    host = product_api_url.split("//")[1].split('/')[0]
    endpoint_base = product_api_url.split('https://' + host)[1]

    global token_manager
    token_manager = TokenManager(
        url=main_url,
        max_retries=4,
        save_token=False,
        save_cookies=False
    )
    global auth_token
    if not auth_token:
        auth_token = token_manager.get_token_instance()
    if auth_token is not None:
        headers = {
            'authority': f'{host}',
            'method': 'GET',
            'path': f'{endpoint_base}',
            'scheme': 'https',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ru-RU',
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json',
            'Origin': 'https://uzum.uz',
            'Priority': 'u=1, i',
            'Referer': 'https://uzum.uz/',
            'Sec-Ch-Ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Sentry-Trace': '7045c04a13404cd1b3abb6633c60702f-b0db85c265fc14ff-0',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'X-Iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7',
            'Connection': 'keep-alive'
        }

        data_list = []
        failed_product_ids = []
        request_attempts = 0
        ind = 0

        def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
            logger.info(f"Server rejected. Attempt number {request_attempts}")
            wait_time = backoff_factor * (2 ** request_attempts)
            logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        logger.info(f'Total products to parse {len(product_ids)}. Parsing...')

        conn = http.client.HTTPSConnection(host)

        while ind < len(product_ids):
            if request_attempts > request_retries:
                logger.error('Exceeded max number of retries!')
                break

            try:
                product_id = product_ids[ind]
                endpoint = f'{endpoint_base}{product_id}'
                headers['path'] = f'{endpoint}'

                conn.request("GET", endpoint, headers=headers)
                response = conn.getresponse()
                if response.status == 200:
                    response_data = response.read()
                    content_encoding = response.getheader('Content-Encoding')
                    if content_encoding:
                        response_data = decompress_http_response(
                            response_data, content_encoding)
                    decoded_data = response_data.decode('utf-8')

                    if not decoded_data:
                        raise ValueError(
                            "Empty response data from product API")

                    json_data = json.loads(decoded_data)

                    if 'errors' in json_data:
                        error_messages = [
                            error.get('message', 'Unknown error') for error in json_data['errors']]
                        error_429 = False
                        for error_message in error_messages:
                            logger.error(f'Product API Error: {error_message}')
                            if '429' in error_message:
                                error_429 = True

                        if error_429:
                            status = 429
                            wait_with_backoff(request_attempts, backoff_factor)
                            if request_attempts == 0:
                                conn.close()
                                new_token = token_manager.get_token_instance()
                                if new_token is not None:
                                    auth_token = new_token
                                    headers['Authorization'] = f'Bearer {
                                        auth_token}'
                                conn = http.client.HTTPSConnection(host)
                            request_attempts += 1
                            continue

                    data, errors = parse_product(json_data)
                    if data:
                        data_list.append(data)
                    else:
                        logger.error(
                            f'Could not parse data from product ID {product_id}.')
                        logger.error(f'Errors found: {errors}')
                        failed_product_ids.append(product_id)

                    request_attempts = 0
                    ind += 1
                    if ind % 100 == 0:
                        logger.info(f'Processed {ind} products.')

                elif response.status == 401:
                    logger.info(
                        f"{response.status}: Authorization failed during the product API request; retrieving a new token...")
                    conn.close()
                    wait_with_backoff(request_attempts, backoff_factor)
                    auth_token = token_manager.get_token_instance()
                    headers['Authorization'] = f'Bearer {auth_token}'
                    request_attempts += 1
                    conn = http.client.HTTPSConnection(host)
                elif response.status == 429:
                    logger.info(
                        "429: Blocked by a server due to too many requests.")
                    wait_with_backoff(request_attempts, backoff_factor)
                    request_attempts += 1
                    continue
                else:
                    raise ValueError(f"Bad response status on a product API: {
                                     response.status}")
            except Exception as e:
                logger.error(f'Failed to receive data from a product API: {e}')
                break

        conn.close()

    else:
        raise FileNotFoundError("Failed to get authorization token.")

    if data_list:
        logger.info(f'Finished parsing {len(data_list)} products.')
        save_csv(data_list, 'products', 'products')
    else:
        logger.warning('Zero products parsed!')
    if failed_product_ids:
        logger.warning(f'Failed to parse {len(failed_product_ids)} products.')
        save_csv(failed_product_ids, 'failed_product_ids', 'products')

    return data_list, failed_product_ids


def fetch_data() -> None:
    """
    Fetch data from the API and handle errors, retries, and backoff.

    This function fetches root categories, leaf categories, product IDs, and product details.
    """
    start_time = time.time()
    try:
        root_categories = get_root_categories()
        if root_categories is None:
            logger.warning(f"Failed to fetch root-categories from {
                           main_url}, loading the most recent saved root-categories.")
            root_categories = load_last_saved_root_categories(
                f"{data_dir}/root_categories")
            if root_categories is not None:
                logger.info(
                    "Successfully loaded the most recent root-categories.")
            else:
                raise FileNotFoundError("Failed to load root-categories.")

        logger.info("Retrieving leaf-categories...")
        leaf_categories = find_leaf_categories(root_categories)
        if leaf_categories:
            logger.info(f"Extracted {len(leaf_categories)
                                     } categories from root-categories.")
            save_csv(leaf_categories, 'leaf_categories', 'category_ids')
        else:
            raise AttributeError("Leaf categories not found")

        logger.info("Retrieving IDs...")
        product_ids = None  # fetch_product_ids_by_categories(leaf_categories)
        if product_ids is None or not product_ids:
            logger.warning(f"Failed to fetch product IDs from {
                           main_url}, loading most recent saved ids.")
            product_ids = load_last_saved_csv(
                f'{data_dir}/product_ids', 'product_ids')
            if product_ids is not None:
                logger.info("Successfully loaded the most recent product IDs.")
            else:
                raise FileNotFoundError("Failed to load product IDs.")

        logger.info('Parsing products...')
        products, failed_products_ids = fetch_products(product_ids)

    except Exception as e:
        logger.error(f"Could not fetch data: {e} Exiting...")
    finally:
        end_time = time.time()
        logger.info(f"Total execution time: {
                    end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    try:
        fetch_data()
    except Exception as e:
        logger.error(f'Data fetching failed: {e}')
