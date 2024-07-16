import http.client
import time
import json
from datetime import datetime
import os
import glob
import csv
import logging
import zlib
import brotli
from fake_useragent import UserAgent
from typing import List, Tuple, Dict, Any
import sys

from token_manager import TokenManager

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

data_dir = "data"

token_manager = None


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


def parse_product(json_data: Dict[str, Any], main_url: str = "https.uzum.uz/ru") -> Tuple[Dict[str, Any], Dict[str, str] | str]:
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


def fetch_products(p_ids: List[int], request_retries: int = 8, backoff_factor: int = 1, product_api_url: str = "https://api.uzum.uz/api/v2/product/", main_url: str = "https://uzum.uz/ru", save_data: bool = True, **kwargs) -> Tuple[List[Dict[str, Any]], List[int]]:
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
        'User-Agent': ua.random if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
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

    logger.info(f'Total products to parse {len(p_ids)}. Parsing...')

    try:
        conn = http.client.HTTPSConnection(host)
        while ind < len(p_ids):
            if request_attempts > request_retries:
                logger.error('Exceeded max number of retries!')
                break

            try:
                product_id = p_ids[ind]
                endpoint = f'{endpoint_base}{product_id}'
                headers['path'] = f'{endpoint}'

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
                            logger.error(f'Product API Error: {
                                error_message}')
                            if '429' in error_message:
                                error_429 = True

                        if error_429:
                            status = 429
                            wait_with_backoff(
                                request_attempts, backoff_factor)
                            if request_attempts == 0:
                                conn.close()
                                headers['User-Agent'] = ua.random
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
                    headers['User-Agent'] = ua.random
                    wait_with_backoff(request_attempts, backoff_factor)
                    request_attempts += 1
                    continue
                else:
                    raise ValueError(f"Bad response status on a product API: {
                        response.status}")
            except Exception as e:
                logger.error(
                    f'Failed to receive data from a product API: {e}')
                break
    except Exception as e:
        logger.error(f"In fetch_product: {e}")
    finally:
        conn.close()

    if data_list:
        logger.info(f'Finished parsing {len(data_list)} products.')
        if save_data:
            save_csv(data_list, 'products', 'products')
    else:
        logger.warning('Zero products parsed!')
    if failed_product_ids:
        logger.warning(f'Failed to parse {len(failed_product_ids)} products.')
        if save_data:
            save_csv(failed_product_ids, 'failed_product_ids', 'products')

    return data_list, failed_product_ids


def are_integers(args):
    for arg in args:
        try:
            int(arg)
        except ValueError:
            return False
    return True


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if are_integers(arguments):
        product_list = []
        for product in arguments:
            product_list.append(product)
        logger.info("Starting parse products from the input...")
        try:
            fetch_products(product_list)
        except Exception as e:
            logger.error(f"In {sys.argv[0]}->main: {e}")
    else:
        logger.error("Wrong input arguments.")
