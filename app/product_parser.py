import http.client
import time
import json
import logging
import logging.config
import zlib
import brotli
from fake_useragent import UserAgent
from typing import List, Tuple, Dict, Any
import sys
import re
import argparse
import configparser
from save_and_load_data import load_last_saved_json, save_to_file
from image_download import download_image
from send_data_to_db import send_message

import base64

from token_manager import TokenManager

# Configure logging
try:
    logging.config.fileConfig('configs/logging.conf')
    logger = logging.getLogger('main')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
brands_dir = config.get('storage', 'brands_sub_dir')
product_ids_dir = config.get('storage', 'product_ids_sub_dir')
products_dir = config.get('storage', 'products_sub_dir')
images_dir = config.get('storage', 'images_sub_dir')


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


def parse_product(json_data: Dict[str, Any], brands_by_category, main_url: str = "https://uzum.uz/ru") -> Tuple[Dict[str, Any], Dict[str, str] | str]:
    """
    Parse product information from the given JSON data.

    Args:
        json_data (Dict[str, Any]): The JSON data.

    Returns:
        Tuple[Dict[str, Any], Dict[str, str] | str]: The parsed product data and any error messages.
    """
    def find_oldest_ancestor(category_data):
        current_category = category_data['category']
        while current_category['parent'] is not None:
            current_category = current_category['parent']
        return current_category['id']

    def find_keywords_in_title(title, keywords):
        matches = []
        for keyword in keywords:
            # Use regex to find full word match
            if re.search(r'\b' + re.escape(keyword) + r'\b', title):
                matches.append(keyword)
        return matches

    def get_hierarchical_parents(category) -> Dict[str, Any]:
        if not category or 'parent' not in category or category['parent'] is None:
            return None
        parent = category['parent']
        return {
            'id': parent.get('id', None),
            'title': parent.get('title', None),
            'productAmount': parent.get('productAmount', None),
            'parent': get_hierarchical_parents(parent)
        }

    try:
        payload = json_data.get('payload', {}).get('data', {})
        characteristic_data = payload.get('characteristics', [])

        hierarchical_parents = get_hierarchical_parents(payload.get('category', {}))

        if not payload:
            raise ValueError("Payload or data is missing in the JSON file.")

        if payload.get('category', {}).get('title', None).lower() == "Смартфоны Apple iPhone(iOS)".lower():
            brand = ["Apple"]
        else:
            brand = find_keywords_in_title(payload.get('title', None), brands_by_category[f'{find_oldest_ancestor(payload)}']) if brands_by_category else ''

        # image_path = download_image(payload.get('photos', {})[0].get('photo', {}).get('800', {}).get('high', None), payload.get('id', None), f'{data_dir}/{images_dir}')

        result = {
            'id': payload.get('id', None),
            'title': payload.get('title', None),
            'brand': ', '.join(brand),
            'category': {
                'id': payload.get('category', {}).get('id', None),
                'title': payload.get('category', {}).get('title', None),
                'productAmount': payload.get('category', {}).get('productAmount', None),
                'parent': hierarchical_parents
            },
            'rating': payload.get('rating', None),
            'reviewsAmount': payload.get('reviewsAmount', None),
            'ordersAmount': payload.get('ordersAmount', None),
            'totalAvailableAmount': payload.get('totalAvailableAmount', None),
            'url': f'{main_url}/product/{payload.get("id", None)}',
            # 'photo': image_path,
            'photo': payload.get('photos', {})[0].get('photo', {}).get('800', {}).get('high', None),
            'skuList': [{
                'characteristics': [{
                    'id': characteristic_data[char.get('charIndex', None)]['id'],
                    'title': characteristic_data[char.get('charIndex', None)]['title'],
                    'values': characteristic_data[char.get('charIndex', None)]['values'][char.get('valueIndex', None)]
                } for char in sku.get('characteristics', [])],
                'id': sku.get('id', None),
                'availableAmount': sku.get('availableAmount', None),
                'fullPrice': sku.get('fullPrice', None),
                'purchasePrice': sku.get('purchasePrice', None)
            } for sku in payload.get('skuList', [])],
            'seller': [{
                'id': payload.get('seller', {}).get('id', None),
                'title': payload.get('seller', {}).get('title', None),
                'rating': payload.get('seller', {}).get('rating', None),
                'reviews': payload.get('seller', {}).get('reviews', None),
                'orders': payload.get('seller', {}).get('orders', None),
            }],
        }

        # Check for null values and add error messages if any
        error_messages = {}
        for key, value in result.items():
            if value is None:
                error_messages[key] = f"{key} is missing or null in the JSON file."

        if error_messages:
            return None, error_messages

        return result, None

    except Exception as e:
        return None, str(e)


def fetch_products(p_ids: List[int],
                   request_retries: int = 15,
                   backoff_factor: int = 1,
                   product_api_url: str = "https://api.uzum.uz/api/v2/product/",
                   main_url: str = "https://uzum.uz/ru",
                   save_data: bool = True,
                   **kwargs) -> Tuple[List[Dict[str, Any]], List[int]]:
    """
    Fetch product details for the given product IDs with retries and backoff on failure.

    Args:
        product_ids (List[int]): List of product IDs to fetch.
        request_retries (int, optional): Number of retries for the request.
        backoff_factor (int, optional): Backoff factor for retries.

    Returns:
        Tuple[List[Dict[str, Any]], List[int]]: A tuple containing the list of product details and the list of failed product IDs.
    """
    brands_by_category = load_last_saved_json(f'{data_dir}/{brands_dir}')

    host = product_api_url.split("//")[1].split('/')[0]
    endpoint_base = product_api_url.split('https://' + host)[1]

    logger.info("Initiating tokenManager in 'fetch_products'.")
    token_manager = TokenManager(
        url=main_url,
        max_retries=kwargs.get('token_retries', 5),
        save_token=kwargs.get('save_token', False),
        save_cookies=False
    )
    auth_token = token_manager.get_token_instance()
    if auth_token is None:
        raise FileNotFoundError("Failed to get authorization token.")

    ua = UserAgent()
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
        'Origin': f'{main_url}',
        'Priority': 'u=1, i',
        'Referer': f'{main_url}',
        'Sec-Fetch-Site': 'same-site',
        'Sentry-Trace': '7045c04a13404cd1b3abb6633c60702f-b0db85c265fc14ff-0',
        'User-Agent': ua.random,  # if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'X-Iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7',
        'Connection': 'keep-alive'
    }

    data_list = []
    total_data_list = []
    failed_product_ids = []
    request_attempts = 0
    ind = 0

    def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
        logger.warning(f"Server rejected. Attempt number {request_attempts}")
        wait_time = backoff_factor * (2 ** request_attempts)
        logger.info(f"Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    logger.info(f'Total products to parse {len(p_ids)}. Parsing...')

    try:
        conn = http.client.HTTPSConnection(host)

        # proxy = "user210707:6qml5v@193.28.183.102:6176"
        # auth_part, proxy_address = proxy.split("@")
        # username, password = auth_part.split(":")
        # proxy_host, proxy_port = proxy_address.split(":")
        # proxy_port = int(proxy_port)
        # # Encode credentials for Proxy-Authorization header
        # credentials = f"{username}:{password}"
        # encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        # # Set up a connection to the proxy
        # conn = http.client.HTTPSConnection(proxy_host, proxy_port)

        # # Set up a tunnel to the target host using the CONNECT method
        # conn.set_tunnel(host, headers={
        #     'Proxy-Authorization': f'Basic {encoded_credentials}'
        # })

        # Store data main structure
        data_to_save = {
            'platform': 'UZUM',
            'data': []
        }
        save_to_file(data_to_save, 'products', products_dir)

        while ind < len(p_ids):
            if request_attempts > request_retries:
                logger.error('Exceeded max number of retries!')
                break

            try:
                product_id = p_ids[ind]
                endpoint = f'{endpoint_base}{product_id}'
                headers['path'] = f'{endpoint}'

                headers['User-Agent'] = ua.random

                conn.request("GET", endpoint, headers=headers)
                response = conn.getresponse()
                if response.status == 200:
                    response_data = response.read()
                    content_encoding = response.getheader(
                        'Content-Encoding')
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
                            logger.warning("429 (JSON errors): Blocked by the server due to too many requests.")
                            conn.close()
                            wait_with_backoff(
                                request_attempts, backoff_factor)
                            if request_attempts == 0:
                                new_token = token_manager.get_token_instance()
                                if new_token is not None:
                                    auth_token = new_token
                                    headers['Authorization'] = f'Bearer {
                                        auth_token}'
                            request_attempts += 1
                            # headers['User-Agent'] = ua.random
                            conn = http.client.HTTPSConnection(host)

                            # proxy = "user210707:6qml5v@193.28.183.102:6176"
                            # auth_part, proxy_address = proxy.split("@")
                            # username, password = auth_part.split(":")
                            # proxy_host, proxy_port = proxy_address.split(":")
                            # proxy_port = int(proxy_port)
                            # # Encode credentials for Proxy-Authorization header
                            # credentials = f"{username}:{password}"
                            # encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
                            # # Set up a connection to the proxy
                            # conn = http.client.HTTPSConnection(proxy_host, proxy_port)

                            # # Set up a tunnel to the target host using the CONNECT method
                            # conn.set_tunnel(host, headers={
                            #     'Proxy-Authorization': f'Basic {encoded_credentials}'
                            # })

                            continue

                    data, errors = parse_product(json_data, brands_by_category)
                    if data:
                        data_list.append(data)
                        data_to_send = {
                            'platform': 'UZUM',
                            'data': [data]
                        }
                        # send to RabbitMQ
                        try:
                            send_message(data_to_send, host_name="localhost")
                        except Exception as e:
                            logger.error(f'Sending RabbitMQ message to broker failed:{e}')

                    else:
                        logger.error(f'Could not parse data from product ID {product_id}.')
                        logger.error(f'Errors found: {errors}')
                        failed_product_ids.append(product_id)

                    request_attempts = 0
                    ind += 1
                    if ind % 15 == 0:
                        time.sleep(2.5)
                    if ind % 100 == 0:
                        if data_list and save_data:
                            data_to_save = {
                                'data': data_list
                            }
                            save_to_file(data_to_save, 'products', products_dir, override_file=False)
                        total_data_list.extend(data_list)
                        data_list = []
                        logger.info(f'Processed {ind} products.')
                        time.sleep(1)

                elif response.status == 401:
                    logger.warning(f"{response.status}: Authorization failed during the product API request; retrieving a new token...")
                    conn.close()
                    wait_with_backoff(request_attempts, backoff_factor)
                    auth_token = token_manager.get_token_instance()
                    headers['Authorization'] = f'Bearer {auth_token}'
                    request_attempts += 1

                    # headers['User-Agent'] = ua.random
                    conn = http.client.HTTPSConnection(host)

                    # proxy = "user210707:6qml5v@193.28.183.102:6176"
                    # auth_part, proxy_address = proxy.split("@")
                    # username, password = auth_part.split(":")
                    # proxy_host, proxy_port = proxy_address.split(":")
                    # proxy_port = int(proxy_port)
                    # # Encode credentials for Proxy-Authorization header
                    # credentials = f"{username}:{password}"
                    # encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
                    # # Set up a connection to the proxy
                    # conn = http.client.HTTPSConnection(proxy_host, proxy_port)

                    # # Set up a tunnel to the target host using the CONNECT method
                    # conn.set_tunnel(host, headers={
                    #     'Proxy-Authorization': f'Basic {encoded_credentials}'
                    # })

                elif response.status == 429:
                    retry_time = int(response.headers.get("Retry-After", 1))
                    conn.close()
                    logger.warning("429: Blocked by the server due to too many requests.")
                    if retry_time > 0:
                        logger.warning(f"Received waiting time: {retry_time} seconds")
                        time.sleep(retry_time)
                    else:
                        wait_with_backoff(request_attempts, backoff_factor)
                    request_attempts += 1

                    # headers['User-Agent'] = ua.random
                    conn = http.client.HTTPSConnection(host)

                    # proxy = "user210707:6qml5v@193.28.183.102:6176"
                    # auth_part, proxy_address = proxy.split("@")
                    # username, password = auth_part.split(":")
                    # proxy_host, proxy_port = proxy_address.split(":")
                    # proxy_port = int(proxy_port)
                    # # Encode credentials for Proxy-Authorization header
                    # credentials = f"{username}:{password}"
                    # encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
                    # # Set up a connection to the proxy
                    # conn = http.client.HTTPSConnection(proxy_host, proxy_port)

                    # # Set up a tunnel to the target host using the CONNECT method
                    # conn.set_tunnel(host, headers={
                    #     'Proxy-Authorization': f'Basic {encoded_credentials}'
                    # })

                    continue
                else:
                    raise ValueError(f"Bad response status on a product API: {
                        response.status}")
            except Exception as e:
                if save_data and data_list:
                    data_to_save = {
                        'data': data_list
                    }
                    save_to_file(data_to_save, 'products', products_dir, override_file=False)
                    total_data_list.extend(data_list)
                    data_list = []
                logger.error(f'Failed to receive data from a product API: {e}')
                break
    except Exception as e:
        logger.error(f"In fetch_product: {e}")
    finally:
        conn.close()

    if data_list:
        total_data_list.extend(data_list)
        logger.info(f'Finished parsing {len(total_data_list)} products.')
        if save_data:
            data_to_save = {
                'data': data_list
            }
            save_to_file(data_to_save, 'products', products_dir, override_file=False)
    else:
        logger.warning('Zero products parsed!')
    if failed_product_ids:
        logger.warning(f'Failed to parse {len(failed_product_ids)} products.')
        if save_data:
            save_to_file(failed_product_ids, 'failed_product_ids', products_dir, file_type="JSON")

    return total_data_list, failed_product_ids


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Processing of product data.')
    parser.add_argument('product_ids', metavar='N', type=int, nargs='*',
                        help='an integer for the product ID to process')
    parser.add_argument('-l', '--load', metavar='FILENAME', type=str, nargs='?',
                        const='product_ids', help='Load the last saved product IDS, specify a file name to load from data/product_ids.')

    args = parser.parse_args()
    product_list = []
    if args.load:
        file_name = args.load
        if file_name:
            logger.info(f"Loading IDs data from file: {file_name}")
            product_list = load_last_saved_json(directory=f'{data_dir}/{product_ids_dir}', file_name=file_name)
        else:
            logger.info(
                f"Loading the last saved IDs from: {data_dir}/product_ids")
            product_list = load_last_saved_json(directory=f'{data_dir}/{product_ids_dir}')
    elif args.product_ids:
        logger.info(f'Parsing product with ID: {args.product_ids}')
        product_list = args.product_ids
    else:
        logger.info(f"Loading last saved product IDs in {
                    data_dir}/product_ids.")
        product_list = load_last_saved_json(directory=f'{data_dir}/{product_ids_dir}')

    if product_list:
        # brands_by_category = load_last_saved_json(f'{data_dir}/{brands_dir}')
        # if not brands_by_category:
        #     logger.warning("Could not load main categories brands")

        logger.info("Starting to parse products from the input...")
        try:
            fetch_products(product_list)
        except Exception as e:
            logger.error(f"In {sys.argv[0]}->main: {e}")
