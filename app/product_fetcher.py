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
import uuid
from typing import Tuple
from save_and_load_data import load_last_saved_json, save_to_file
from image_download import download_image
from send_data_to_db import send_message
from proxy_manager import ProxyManager
from token_manager import TokenManager


class ProductFetcher:
    def __init__(self,
                 config_path: str = 'configs/app.conf',
                 logging_path: str = 'configs/logging.conf',
                 use_direct_connection: bool = None,
                 proxy_timeout: float = None,
                 proxy_manager_timeout: int = None,
                 batch_size: int = None):
        # Configure logging
        try:
            logging.config.fileConfig(logging_path)
            self.logger = logging.getLogger('main')
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger()
            self.logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

        # Read configuration
        self.config = configparser.ConfigParser()
        self.config.read(config_path)

        # Initialize attributes
        self.data_dir = self.config.get('storage', 'data_directory')
        # self.brands_dir = self.config.get('storage', 'brands_sub_dir')
        self.product_ids_dir = self.config.get('storage', 'product_ids_sub_dir')
        self.products_dir = self.config.get('storage', 'products_sub_dir')
        self.images_dir = self.config.get('storage', 'images_sub_dir')

        self.main_url = self.config.get('urls', 'main_url')
        self.product_api_url = self.config.get('urls', 'product_api_url')

        # Fetching alg parameters
        self.use_direct_connection = use_direct_connection if use_direct_connection else self.config.getboolean('prdoduct_fetching', 'use_direct_connection')
        self.proxy_timeout = proxy_timeout if proxy_timeout else float(self.config.get('prdoduct_fetching', 'proxy_timeout'))
        self.proxy_manager_timeout = proxy_manager_timeout if proxy_manager_timeout else int(self.config.get('prdoduct_fetching', 'proxy_manager_timeout'))
        self.batch_size = batch_size if batch_size else int(self.config.get('prdoduct_fetching', 'batch_size'))

        self.brands_by_category = load_last_saved_json(f'{self.data_dir}/{self.config.get('storage', 'brands_sub_dir')}')

        # Managers
        self.token_manager = None
        self.proxy_manager = None
        self.auth_token = None

        self.ua = UserAgent()

        self.headers = {
            'authority': f'{self.product_api_url.split("//")[1].split('/')[0]}',
            'method': 'GET',
            'path': f'{self.product_api_url.split('https://' + self.product_api_url.split("//")[1].split('/')[0])[1]}',
            'scheme': 'https',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'ru-RU',
            'Authorization': f'Bearer ',
            'Content-Type': 'application/json',
            'Origin': f'{self.main_url}',
            'Priority': 'u=1, i',
            'Referer': f'{self.main_url}',
            'Sec-Fetch-Site': 'same-site',
            'Sentry-Trace': str(uuid.uuid4()),
            'User-Agent': self.ua.random,  # if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'X-Iid': str(uuid.uuid4()),
            # 'Connection': 'keep-alive'
        }

    def initialize_managers(self, **kwargs):
        if not self.token_manager:
            self.logger.debug("Initializing TokenManager in ProductFetcher")
            self.token_manager = TokenManager(
                url=kwargs.get('url', self.main_url),
                max_retries=kwargs.get('token_retries', 5),
                save_token=kwargs.get('save_token', False),
                save_cookies=False
            )
        if not self.proxy_manager and not self.use_direct_connection:
            self.logger.debug("Initializing ProxyManager in ProductFetcher")
            self.proxy_manager = ProxyManager.from_json_file(self.proxy_dir)

    def decompress_http_response(self, response_data: bytes, encoding: str) -> bytes:
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

    def parse_product(self, json_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str] | str]:
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
            if json_data['payload'] == None:
                if 'errors' in json_data:
                    detailed_message = [error.get('detailMessage') for error in json_data['errors']]
                    if detailed_message is not None:
                        raise AttributeError(", ".join(detailed_message))
                raise AttributeError(f"product not found")
            payload = json_data.get('payload', {}).get('data', {})
            characteristic_data = payload.get('characteristics', [])

            hierarchical_parents = get_hierarchical_parents(payload.get('category', {}))

            if not payload:
                raise ValueError("Payload or data is missing in the JSON file.")

            if payload.get('category', {}).get('title', None).lower() == "Смартфоны Apple iPhone(iOS)".lower():
                brand = ["Apple"]
            else:
                brand = find_keywords_in_title(payload.get('title', None), self.brands_by_category[f'{find_oldest_ancestor(payload)}']) if self.brands_by_category else ''

            # image_path = download_image(payload.get('photos', {})[0].get('photo', {}).get('800', {}).get('high', None), payload.get('id', None), f'{data_dir}/{images_dir}')

            result = {
                'id': payload.get('id', None),
                'title': payload.get('title', None),
                'titleUz': payload.get('localizableTitle', None).get('uz', None),
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
                'url': f'{self.main_url}/product/{payload.get("id", None)}',
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

        except AttributeError as e:
            return None, str(e)
        except Exception as e:
            return None, str(e)

    def fetch_products(self,
                       p_ids: List[int],
                       ind: int = 0,
                       request_retries: int = 10,
                       backoff_factor: int = 1,
                       save_data: bool = True,
                       **kwargs) -> Tuple[List[Dict[str, Any]], List[int]]:
        """
        Fetch product details for the given product IDs with retries and backoff on failure.

        Args:
            product_ids (List[int]): List of product IDs to fetch.
            ind (int): The index to start from
            request_retries (int, optional): Number of retries for the request.
            backoff_factor (int, optional): Backoff factor for retries.

        Returns:
            Tuple[List[Dict[str, Any]], List[int]]: A tuple containing the list of product details and the list of failed product IDs.
        """
        start_time = time.time()

        host = self.product_api_url.split("//")[1].split('/')[0]
        endpoint_base = self.product_api_url.split('https://' + host)[1]

        self.initialize_managers()

        if self.auth_token is None:
            self.auth_token = self.token_manager.get_token_instance()
            if self.auth_token is None:
                raise FileNotFoundError("Failed to get authorization token.")

        self.headers["Authorization"] = f'Bearer {self.auth_token}'

        data_list = []
        total_data_list = []
        failed_product_ids = []
        request_attempts = 0
        # ind = 0
        status = 0

        conn = None
        current_proxy_ip = None
        proxy_ind = 0
        proxy_timeout = self.proxy_timeout
        proxy_manager_timeout = self.proxy_manager_timeout
        # use_direct_connection = False  # False for no proxy connection
        # batch_size = 10

        # Store data main structure
        data_to_save = {
            'platform': 'UZUM',
            'data': []
        }
        save_to_file(data_to_save, 'products', self.products_dir)

        def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
            self.logger.warning(f"Server rejected. Attempt number {request_attempts}")
            wait_time = backoff_factor * (2 ** request_attempts)
            self.logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        def make_connection(timeout: float = proxy_timeout if proxy_timeout else 10,
                            pm_timeout: int = proxy_manager_timeout if proxy_manager_timeout else 10,
                            put_to_sleep: bool = True
                            ) -> Tuple[http.client.HTTPSConnection, str]:
            nonlocal conn
            nonlocal current_proxy_ip
            nonlocal proxy_ind

            def direct_connection() -> http.client.HTTPSConnection:
                if request_attempts > 0:
                    wait_with_backoff(request_attempts, backoff_factor)
                return http.client.HTTPSConnection(host)

            if not self.use_direct_connection:
                if conn is not None:  # Close the previous connection before establishing a new one
                    self.logger.debug(f"Closing connection for batch {ind // self.batch_size}")
                    conn.close()
                    if current_proxy_ip and put_to_sleep:
                        self.logger.debug(f"Setting to sleep proxy {current_proxy_ip}")
                        self.proxy_manager.sleep_proxy(current_proxy_ip, timeout)
                        proxy_ind = 0
                self.logger.debug(f"Establishing connection for batch {ind // self.batch_size + 1}")
                self.headers['User-Agent'] = self.ua.random
                try:
                    self.logger.debug(f"Picking a proxy and establishing a connection")
                    conn, current_proxy_ip = self.proxy_manager.make_connection(host, pm_timeout)
                    return conn, current_proxy_ip
                except:
                    self.logger.warning(f"No proxy connection!")  # Establishing direct connection to {host}")
                    # conn = direct_connection()
                    # current_proxy_ip = None

            self.logger.debug(f"Establishing direct connection to {host}")
            conn = direct_connection()

            return conn, current_proxy_ip

        self.logger.info(f'Total products to parse {len(p_ids)}. Parsing...')

        try:
            while ind < len(p_ids):
                if request_attempts > request_retries:
                    self.logger.error('Exceeded max number of retries!')
                    break
                try:
                    if proxy_ind % self.batch_size == 0:
                        conn, current_proxy_ip = make_connection()

                    product_id = p_ids[ind]
                    endpoint = f'{endpoint_base}{product_id}'
                    self.headers['path'] = f'{endpoint}'

                    conn.request("GET", endpoint, headers=self.headers)
                    response = conn.getresponse()

                    if response.status == 200:
                        response_data = response.read()
                        content_encoding = response.getheader('Content-Encoding')
                        if content_encoding:
                            response_data = self.decompress_http_response(response_data, content_encoding)
                        decoded_data = response_data.decode('utf-8')

                        if not decoded_data:
                            raise ValueError("Empty response data from product API")

                        json_data = json.loads(decoded_data)
                        # save_to_file(json_data, "pr_response_557141", "")
                        if 'errors' in json_data:
                            save_to_file(json_data, f"response_error_{product_id}", "products")
                            error_messages = [error.get('message', 'Unknown error') for error in json_data['errors']]
                            error_429 = False
                            for error_message in error_messages:
                                self.logger.warning(f'Product API Error: {error_message}')
                                if '429' in error_message:
                                    error_429 = True

                            if error_429:
                                retry_time = int(response.headers.get("Retry-After", 1))
                                self.logger.warning(f"429 (JSON errors): Blocked by the server due to too many requests. Server cool down time: {retry_time}")
                                # wait_with_backoff(request_attempts, backoff_factor)

                                proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                                conn, current_proxy_ip = make_connection(timeout=retry_time)

                                request_attempts += 1

                                continue

                        data, errors = self.parse_product(json_data)
                        if data:
                            data_list.append(data)
                            data_to_send = {
                                'platform': 'UZUM',
                                'data': [data]
                            }

                        else:
                            self.logger.warning(f'Could not parse data from product ID {product_id}: {errors}')
                            failed_product_ids.append({f'{product_id}': errors})

                        request_attempts = 0
                        proxy_manager_timeout = 10
                        proxy_ind += 1
                        ind += 1

                        if ind % self.batch_size == 0:
                            self.logger.debug(f"Processed {ind} products.")
                        if ind % 100 == 0:
                            if data_list and save_data:
                                data_to_save = {
                                    'data': data_list
                                }
                                save_to_file(data_to_save, 'products', self.products_dir, override_file=False)
                            total_data_list.extend(data_list)
                            data_list = []
                            self.logger.debug(f'Processed {ind} products.')

                    elif response.status == 401:
                        self.logger.warning(f"{response.status}: Authorization failed during the product API request; retrieving a new token...")
                        # wait_with_backoff(request_attempts, backoff_factor)
                        self.auth_token = self.token_manager.get_token_instance()
                        self.headers['Authorization'] = f'Bearer {self.auth_token}'
                        request_attempts += 1
                        if request_attempts > 1:
                            conn, current_proxy_ip = make_connection()
                        else:
                            conn, current_proxy_ip = make_connection(put_to_sleep=False)

                    elif response.status == 429:  # need to avoid this
                        retry_time = int(response.headers.get("Retry-After", 1))
                        self.logger.warning(f"429 (JSON errors): Blocked by the server due to too many requests. Server cool down time: {retry_time}")
                        # wait_with_backoff(request_attempts, backoff_factor)
                        request_attempts += 1

                        proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                        conn, current_proxy_ip = make_connection(timeout=(retry_time))

                        continue
                    else:
                        request_attempts += 1
                        if request_attempts > request_retries:
                            raise ValueError(f"Bad response status on a product API: {response.status}")
                        self.logger.warning(f"Bad response status on a product API: {response.status}, retrying...")
                        wait_with_backoff(request_attempts=request_attempts, backoff_factor=backoff_factor)
                        continue
                except Exception as e:
                    self.logger.error(f'Failed to receive data from a product API for product ID {product_id}: {e}')
                    # status = 1
                    request_attempts += 1
                    if request_attempts > request_retries:
                        self.logger.error("Exceeded maximum number of retries! Exiting parser...")

                        if save_data and data_list:
                            data_to_save = {
                                'data': data_list
                            }
                            save_to_file(data_to_save, 'products', self.products_dir, override_file=False)
                            total_data_list.extend(data_list)
                            data_list = []
                        break
                    wait_with_backoff(request_attempts=request_attempts, backoff_factor=backoff_factor)
                    continue
        except Exception as e:
            self.logger.error(f'Error while fetching products:{e}')
        finally:
            if self.proxy_manager:
                self.proxy_manager.shutdown_scheduler()
            if conn is not None:
                conn.close()

        if data_list:
            total_data_list.extend(data_list)
            self.logger.info(f'Finished parsing {len(total_data_list)} products.')
            if save_data:
                data_to_save = {
                    'data': data_list
                }
                save_to_file(data_to_save, 'products', self.products_dir, override_file=False)
        else:
            self.logger.warning(f'{len(total_data_list) if len(total_data_list) else "Zero"} products parsed!')
        if failed_product_ids:
            self.logger.warning(f'Failed to parse {len(failed_product_ids)} products.')
            if save_data:
                save_to_file(failed_product_ids, 'failed_product_ids', self.products_dir, file_type="JSON")

        end_time = time.time()
        self.logger.info(f"Product parser executing time: {end_time - start_time:.2f} seconds")

        return total_data_list, failed_product_ids, status

    def run(self, p_ids: List[int]):
        self.logger.info("Starting to fetch and parse products")
        try:
            return self.fetch_products(p_ids)
        except Exception as e:
            self.logger.error(f"In {__file__}->main: {e}")

    def load_ids(self, file_name: str = "", ind: int = 0):
        product_list = load_last_saved_json(directory=f'{self.data_dir}/{self.product_ids_dir}', file_name=file_name)
        if product_list:
            return product_list[ind:]
        else:
            self.logger.error(f"No product IDs found in {self.data_dir}/{self.product_ids_dir}. Try running first 'IdsFetcher' ")
            return None


if __name__ == "__main__":
    product_fetcher = ProductFetcher()

    parser = argparse.ArgumentParser(description='Processing of product data.')
    parser.add_argument('product_ids', metavar='N', type=int, nargs='*',
                        help='an integer for the product ID to process or the path to the product IDs directory')
    parser.add_argument('-l', '--load', metavar='FILENAME', type=str, nargs='?',
                        const='product_ids', help='Load the last saved product IDS, specify a file name to load from data/product_ids.')
    parser.add_argument('-i', '--index', metavar='START_INDEX', type=int, nargs='?',
                        const=0, help='Index in the categories list to start fetching from.')

    args = parser.parse_args()
    product_list = []
    if args.load:
        file_name = args.load
        if file_name:
            product_fetcher.logger.info(f"Loading IDs data from file: {file_name}")
        else:
            product_fetcher.logger.info(f"Loading the last saved IDs from: {product_fetcher.data_dir}/product_ids")
        product_list = product_fetcher.load_ids(file_name, args.index if args.index else 0)
    elif args.product_ids:
        product_fetcher.logger.info(f'Parsing product with ID: {args.product_ids}')
        product_list = args.product_ids
    else:
        # product_fetcher.logger.info(f"Loading last saved product IDs in {product_fetcher.data_dir}/product_ids.")
        # product_list = load_last_saved_json(directory=f'{product_fetcher.data_dir}/{product_fetcher.product_ids_dir}')
        product_fetcher.logger.error("No product IDs provided!")
        product_fetcher.logger.info("Try using -l or --load to load most recent IDs. Or type product ID to parse a specific product.")

    if product_list:
        product_fetcher.logger.info("Starting to parse products from the input...")
        try:
            product_fetcher.fetch_products(product_list)
        except Exception as e:
            product_fetcher.logger.error(f"In {sys.argv[0]}->main: {e}")
