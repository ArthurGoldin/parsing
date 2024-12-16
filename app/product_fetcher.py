import http.client
import time
import json
import logging
import logging.config
import zlib
import brotli
from fake_useragent import UserAgent
from typing import List, Tuple, Dict, Any, Optional
import sys
import re
import argparse
import configparser
import uuid
import os
from datetime import datetime
from save_and_load_data import load_last_saved_json, save_to_file
from send_data_to_db import send_message
from proxy_manager import ProxyManager
from token_manager import TokenManager
from ids_fetcher import IdsFetcher
# from image_download import upload_image_from_url


current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')


class ProductFetcher:
    """
    A class to fetch and parse product information from a given API.

    Attributes:
        config (configparser.ConfigParser): Configuration parser.
        logger (logging.Logger): Logger instance.
        data_dir (str): Directory for storing data.
        product_ids_dir (str): Sub-directory for product IDs.
        products_dir (str): Sub-directory for products.
        images_dir (str): Sub-directory for images.
        main_url (str): Main URL of the platform.
        product_api_url (str): API URL for fetching product data.
        use_direct_connection (bool): Flag to use direct connection.
        proxy_timeout (float): Timeout for proxy connections.
        proxy_manager_timeout (int): Timeout for proxy manager.
        batch_size (int): Number of products to fetch in a batch.
        brands_by_category (Dict[str, Any]): Brands categorized by product categories.
        token_manager (Optional[TokenManager]): Manager for handling tokens.
        proxy_manager (Optional[ProxyManager]): Manager for handling proxies.
        auth_token (Optional[str]): Authorization token.
        ua (UserAgent): User agent generator.
        headers (Dict[str, str]): HTTP headers for requests.
    """

    def __init__(self,
                 proxy_manager: Optional[ProxyManager] = None,
                 token_manager: Optional[TokenManager] = None,
                 config_path: str = config_path,
                 logging_path: str = logging_config_path,
                 use_direct_connection: Optional[bool] = None,
                 proxy_timeout: Optional[float] = None,
                 proxy_manager_timeout: Optional[int] = None,
                 batch_size: Optional[int] = None,
                 package_size: Optional[int] = None) -> None:
        """
        Initialize the ProductFetcher with configuration and logging.

        Args:
            config_path (str, optional): Path to the configuration file. Defaults to 'configs/app.conf'.
            logging_path (str, optional): Path to the logging configuration file. Defaults to 'configs/logging.conf'.
            use_direct_connection (Optional[bool], optional): Whether to use direct connection. Defaults to None.
            proxy_timeout (Optional[float], optional): Timeout for proxy connections. Defaults to None.
            proxy_manager_timeout (Optional[int], optional): Timeout for the proxy manager. Defaults to None.
            batch_size (Optional[int], optional): Number of products to fetch in a batch. Defaults to None.
        """
        # Configure logging
        try:
            logging.config.fileConfig(logging_path)
            self.logger = logging.getLogger('product_fetcher')
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger()
            self.logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

        # Read configuration
        self.config = configparser.ConfigParser()
        self.config.read(config_path)

        # Initialize directories attributes
        self.data_dir = os.path.join(current_dir, self.config.get('storage', 'data_directory'))
        self.product_ids_dir = self.config.get('storage', 'product_ids_sub_dir')
        self.products_dir = self.config.get('storage', 'products_sub_dir')
        self.images_dir = self.config.get('storage', 'images_sub_dir')
        self.proxy_dir = self.config.get('storage', 'proxy_dir')

        # URL
        self.main_url = self.config.get('urls', 'main_url')
        self.product_api_url = self.config.get('urls', 'product_api_url')

        # Accept language
        self.accept_language = 'ru-RU' if 'ru' in str.lower(self.config.get('product_fetching', 'language')) else 'uz-UZ'

        # Broker connection
        self.broker_host = self.config.get('broker', 'host')
        self.broker_port = self.config.get('broker', 'port')

        # Fetching algorithm parameters
        self.use_direct_connection = use_direct_connection if use_direct_connection is not None else \
            self.config.getboolean('product_fetching', 'use_direct_connection')
        self.proxy_timeout = proxy_timeout if proxy_timeout is not None else \
            float(self.config.get('product_fetching', 'proxy_timeout'))
        self.proxy_manager_timeout = proxy_manager_timeout if proxy_manager_timeout is not None else \
            int(self.config.get('product_fetching', 'proxy_manager_timeout'))
        self.batch_size = batch_size if batch_size is not None else \
            int(self.config.get('product_fetching', 'batch_size'))
        self.package_size = package_size if package_size is not None else \
            int(self.config.get('product_fetching', 'package_size'))

        self.brands_by_category = load_last_saved_json(
            f'{self.data_dir}/{self.config.get("storage", "brands_sub_dir")}'
        )

        # Managers
        self.proxy_manager: Optional[ProxyManager] = proxy_manager
        self.shut_down_proxy_scheduler = False if proxy_manager is not None else True
        self.token_manager: Optional[TokenManager] = token_manager
        self.auth_token: Optional[str] = self.token_manager.get_token_instance() if token_manager is not None else None

        self.ua = UserAgent()

        self.headers: Dict[str, str] = {
            'authority': f'{self.product_api_url.split("//")[1].split("/")[0]}',
            'method': 'GET',
            'path': f'{self.product_api_url.split("https://" + self.product_api_url.split("//")[1].split("/")[0])[1]}',
            'scheme': 'https',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': self.accept_language,
            'Authorization': f'Bearer {self.auth_token if self.auth_token is not None else ""}',
            'Content-Type': 'application/json',
            'Origin': self.main_url,
            'Priority': 'u=1, i',
            'Referer': self.main_url,
            'Sec-Fetch-Site': 'same-site',
            'Sentry-Trace': str(uuid.uuid4()),
            'User-Agent': self.ua.random,
            'X-Iid': str(uuid.uuid4()),
        }

    def initialize_managers(self, **kwargs: Any) -> None:
        """
        Initialize the TokenManager and ProxyManager if they are not already initialized.

        Keyword Args:
            url (str, optional): URL for the TokenManager. Defaults to self.main_url.
            token_retries (int, optional): Maximum retries for the TokenManager. Defaults to 5.
            save_token (bool, optional): Whether to save the token. Defaults to False.
        """
        if not self.proxy_manager and not self.use_direct_connection:
            self.logger.debug("Initializing ProxyManager in IdsFetcher")
            self.proxy_manager = ProxyManager.from_json_file(self.proxy_dir)
        if not self.token_manager:
            self.logger.debug("Initializing TokenManager in IdsFetcher")
            self.token_manager = TokenManager(
                proxy_manager=self.proxy_manager,
                url=kwargs.get('url', self.main_url),
                max_retries=kwargs.get('token_retries', 5),
                save_token=kwargs.get('save_token', False),
                save_cookies=False
            )
            self.auth_token = self.token_manager.get_token_instance()
            if self.auth_token is None:
                raise FileNotFoundError("Failed to get authorization token.")
            self.headers['Authorization'] = f'Bearer {self.auth_token}'

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

    def parse_product(self, json_data: Dict[str, Any], send_img_to_broker) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str] | str]]:
        """
        Parse product information from the given JSON data.

        Args:
            json_data (Dict[str, Any]): The JSON data.

        Returns:
            Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str] | str]]:
                A tuple containing the parsed product data and any error messages.
        """
        def find_oldest_ancestor(category_data: Dict[str, Any]) -> Any:
            current_category = category_data['category']
            while current_category['parent'] is not None:
                current_category = current_category['parent']
            return current_category['id']

        def find_keywords_in_title(title: Optional[str], keywords: List[str]) -> List[str]:
            matches = []
            if title:
                for keyword in keywords:
                    # Use regex to find full word match
                    if re.search(r'\b' + re.escape(keyword) + r'\b', title):
                        matches.append(keyword)
            return matches

        def get_hierarchical_parents(category: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            if not category or 'parent' not in category or category['parent'] is None:
                return None
            parent = category['parent']
            return {
                'id': parent.get('id'),
                'title': {
                    'ru': parent.get('title') if self.accept_language.split('-')[0] == 'ru' else "",
                    'uz': parent.get('title') if self.accept_language.split('-')[0] == 'uz' else "",
                },
                'productAmount': parent.get('productAmount'),
                'parent': get_hierarchical_parents(parent)
            }

        def get_image_url(data: Dict[str, Any], img_type: str = 'high') -> str:
            img_res = ['240', '120', '480', '720', '800', '24034', '80']

            for i in img_res:
                try:
                    img_url = data.get(i, {}).get(img_type, {})
                    if img_url:
                        return img_url
                except Exception as e:
                    self.logger.error(f"Failed to retrieve image URL: {e}")
            return None

        try:
            if json_data.get('payload') is None:
                if 'errors' in json_data:
                    detailed_message = [error.get('detailMessage') for error in json_data['errors']]
                    if detailed_message:
                        raise AttributeError(", ".join(detailed_message))
                raise AttributeError("product not found")

            payload = json_data.get('payload', {}).get('data', {})

            if not payload:
                raise ValueError("Payload or data is missing in the JSON file.")

            # image_path = download_image(payload.get('photos', {})[0].get('photo', {}).get('800', {}).get('high'), payload.get('id'), f'{self.data_dir}/{self.images_dir}')
            # image_path = "N/A"

            img_url = get_image_url(payload.get('photos', {})[0].get('photo', {}))
            if send_img_to_broker:
                obj_key = f'{payload.get('id')}_{img_url.split('/')[-2]}_{img_url.split('/')[-1]}'
                img_data = {
                    "url": img_url,
                    "image_category": 'product',
                    "object_key": obj_key
                }
                try:
                    send_message(img_data, host=self.broker_host, port=self.broker_port, queue_name="products_images")
                except Exception as e:
                    self.logger.error(f"Failed to send image data to broker 'products_images': {e}")

            # if img_url:
            #     try:
            #         obj_key = f'{payload.get('id')}_{img_url.split('/')[-2]}_{img_url.split('/')[-1]}'
            #         res = upload_image_from_url(image_url=img_url, object_key=obj_key)
            #         if res:
            #             image_path = res["url"] if res["url"] is not None else "N/A"
            #     except Exception as e:
            #         self.logger.error(f"Failed to upload an image: {e}")

            characteristic_data = payload.get('characteristics', [])

            hierarchical_parents = get_hierarchical_parents(payload.get('category', {}))

            if payload.get('category', {}).get('title', '').lower() == "Смартфоны Apple iPhone(iOS)".lower():
                brand = ["Apple"]
            else:
                oldest_ancestor_id = find_oldest_ancestor(payload)
                brand_keywords = self.brands_by_category.get(str(oldest_ancestor_id), []) if self.brands_by_category else []
                brand = find_keywords_in_title(payload.get('title'), brand_keywords) if brand_keywords else []

            result: Dict[str, Any] = {
                'id': payload.get('id'),
                'title': {
                    'ru': payload.get('localizableTitle', {}).get('ru'),
                    'uz': payload.get('localizableTitle', {}).get('uz')
                },
                'brand': ', '.join(brand),
                'category': {
                    'id': payload.get('category', {}).get('id'),
                    'title': {
                        'ru': payload.get('category', {}).get('title') if self.accept_language.split('-')[0] == 'ru' else "",
                        'uz': payload.get('category', {}).get('title') if self.accept_language.split('-')[0] == 'uz' else "",
                    },
                    'productAmount': payload.get('category', {}).get('productAmount'),
                    'parent': hierarchical_parents
                },
                'rating': payload.get('rating'),
                'reviewsAmount': payload.get('reviewsAmount'),
                'ordersAmount': payload.get('ordersAmount'),
                'totalAvailableAmount': payload.get('totalAvailableAmount'),
                'url': f'{self.main_url}/product/{payload.get("id")}',
                # 'photo': image_path,
                'photo': img_url,
                'skuList': [{
                    'characteristics': [{
                        'id': characteristic_data[char.get('charIndex')]['id'],
                        'title': {
                            'ru': characteristic_data[char.get('charIndex')]['title'] if self.accept_language.split('-')[0] == 'ru' else "",
                            'uz': characteristic_data[char.get('charIndex')]['title'] if self.accept_language.split('-')[0] == 'uz' else "",
                        },
                        'values': {
                            'id': characteristic_data[char.get('charIndex')]['values'][char.get('valueIndex')]['id'],
                            'title': {
                                'ru': characteristic_data[char.get('charIndex')]['values'][char.get('valueIndex')]['title'] if self.accept_language.split('-')[0] == 'ru' else "",
                                'uz': characteristic_data[char.get('charIndex')]['values'][char.get('valueIndex')]['title'] if self.accept_language.split('-')[0] == 'uz' else ""
                            },
                            'value': characteristic_data[char.get('charIndex')]['values'][char.get('valueIndex')]['value']
                        },
                    } for char in sku.get('characteristics', [])],
                    'id': sku.get('id'),
                    'availableAmount': sku.get('availableAmount'),
                    'fullPrice': sku.get('fullPrice'),
                    'purchasePrice': sku.get('purchasePrice')
                } for sku in payload.get('skuList', [])],
                'seller': [{
                    'id': payload.get('seller', {}).get('id'),
                    'title': payload.get('seller', {}).get('title'),
                    'rating': payload.get('seller', {}).get('rating'),
                    'reviews': payload.get('seller', {}).get('reviews'),
                    'orders': payload.get('seller', {}).get('orders'),
                }],
            }

            # Check for null values and add error messages if any
            error_messages: Dict[str, str] = {}
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
                       send_to_db: bool = True,
                       **kwargs: Any) -> Tuple[int, int]:  # Tuple[List[Dict[str, Any]], List[int], int]:
        """
        Fetch product details for the given product IDs with retries and backoff on failure.

        Args:
            p_ids (List[int]): List of product IDs to fetch.
            ind (int, optional): The index to start from. Defaults to 0.
            request_retries (int, optional): Number of retries for the request. Defaults to 10.
            backoff_factor (int, optional): Backoff factor for retries. Defaults to 1.
            save_data (bool, optional): Whether to save fetched data. Defaults to True.

        Keyword Args:
            Any additional keyword arguments.

        Returns:
            Tuple[int, int]:
                A tuple containing the status code (0 success, 1 failure) and the last processed index in the product IDs list
            x-Tuple[List[Dict[str, Any]], List[int], int]:
                x- A tuple containing the list of product details, the list of failed product IDs, and the status code.
        """
        start_time = time.time()

        host = self.product_api_url.split("//")[1].split('/')[0]
        endpoint_base = self.product_api_url.split(f'https://{host}')[1]

        self.initialize_managers()

        self.headers["User-Agent"] = self.ua.random

        data_list: List[Dict[str, Any]] = []
        # total_data_list: List[Dict[str, Any]] = []
        total_products_count = ind
        product_count = 0
        failed_product_ids: List[int] = []
        request_attempts = 0
        status = 0

        conn: Optional[http.client.HTTPSConnection] = None
        current_proxy_ip: Optional[str] = None
        proxy_ind = 0
        proxy_timeout = self.proxy_timeout
        proxy_manager_timeout = self.proxy_manager_timeout

        def save_data_to(data_list, file_name: Optional[str] = None):
            if save_data:
                data_to_save = {
                    'platform': 'UZUM',
                    'data': data_list
                }
                if file_name is None:
                    file_name = f'{max(0, total_products_count - self.package_size)}-{total_products_count}'
                save_to_file(data_to_save,
                             file_name,
                             f"{self.products_dir}/{datetime.now().strftime("%Y%m%d")}",
                             override_file=True)

        def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
            """
            Wait for a certain period based on the backoff factor and the number of request attempts.

            Args:
                request_attempts (int): The current number of request attempts.
                backoff_factor (float): The backoff factor to calculate wait time.
            """
            self.logger.warning(f"Server rejected. Attempt number {request_attempts}")
            wait_time = min(backoff_factor * (2 ** request_attempts), 2 ** 7)
            self.logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        def make_connection(timeout: float = proxy_timeout if proxy_timeout else 10,
                            pm_timeout: int = proxy_manager_timeout if proxy_manager_timeout else 10,
                            put_to_sleep: bool = True) -> Tuple[http.client.HTTPSConnection, Optional[str]]:
            """
            Establish a new HTTP connection, optionally using a proxy.

            Args:
                timeout (float, optional): Timeout for the connection. Defaults to proxy_timeout or 10.
                pm_timeout (int, optional): Timeout for the proxy manager. Defaults to proxy_manager_timeout or 10.
                put_to_sleep (bool, optional): Whether to put the proxy to sleep after use. Defaults to True.

            Returns:
                Tuple[http.client.HTTPSConnection, Optional[str]]: The HTTPS connection and the proxy IP if used.
            """
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
                except Exception:
                    self.logger.warning("No proxy connection!")
                    # Attempting direct connection if proxy fails
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
                        # save_to_file(json_data, f"pr_response_{product_id}", "")
                        if 'errors' in json_data:
                            save_data_to(json_data, f"response_error_{product_id}")
                            # save_to_file(json_data, f"response_error_{product_id}", "products")
                            error_messages = [error.get('message', 'Unknown error') for error in json_data['errors']]
                            error_429 = False
                            error_401 = False
                            for error_message in error_messages:
                                self.logger.warning(f'Product API Error: {error_message}')
                                if '429' in error_message:
                                    error_429 = True
                                if '401' in error_message:
                                    error_401 = True

                            if error_429:
                                retry_time = int(response.headers.get("Retry-After", 1))
                                self.logger.warning(f"429 (JSON errors): Blocked by the server due to too many requests. Server cool down time: {retry_time}")
                                # wait_with_backoff(request_attempts, backoff_factor)
                                proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                                conn, current_proxy_ip = make_connection(timeout=retry_time)
                                request_attempts += 1
                                continue

                            if error_401:
                                self.logger.warning(f"{response.status}: Authorization failed during the product API request; retrieving a new token...")

                                self.auth_token = self.token_manager.get_token_instance()
                                self.headers['Authorization'] = f'Bearer {self.auth_token}'
                                request_attempts += 1
                                if request_attempts > 1:
                                    conn, current_proxy_ip = make_connection()
                                else:
                                    conn, current_proxy_ip = make_connection(put_to_sleep=False)
                                continue

                        data, errors = self.parse_product(json_data, send_to_db)
                        if data:
                            data_list.append(data)
                            total_products_count += 1
                            product_count += 1
                        else:
                            self.logger.warning(f'Could not parse data from product ID {product_id}: {errors}')
                            failed_product_ids.append(product_id)

                        request_attempts = 0
                        proxy_manager_timeout = 10
                        proxy_ind += 1
                        ind += 1

                        if ind % self.batch_size == 0:
                            self.logger.debug(f"Processed {ind} products.")
                        if len(data_list) % self.package_size == 0:
                            if data_list and save_data:
                                save_data_to(data_list)
                            if send_to_db:
                                data_to_send = {
                                    'platform': 'UZUM',
                                    'data': [data_list]
                                }
                                # Optionally, send data to DB or other services
                                try:
                                    send_message(data_to_send, host=self.broker_host, port=self.broker_port)
                                except Exception as e:
                                    self.logger.error(f"Failed to send to Broker: {e}")
                            data_list = []
                            self.logger.debug(f'Processed {ind} products.')

                    elif response.status == 401:
                        self.logger.warning(f"{response.status}: Authorization failed during the product API request; retrieving a new token...")

                        self.auth_token = self.token_manager.get_token_instance()
                        self.headers['Authorization'] = f'Bearer {self.auth_token}'
                        request_attempts += 1
                        if request_attempts > 1:
                            conn, current_proxy_ip = make_connection()
                        else:
                            conn, current_proxy_ip = make_connection(put_to_sleep=False)
                        continue

                    elif response.status == 429:  # need to avoid this
                        retry_time = int(response.headers.get("Retry-After", 1))
                        self.logger.warning(f"429 (JSON errors): Blocked by the server due to too many requests. Server cool down time: {retry_time}")

                        request_attempts += 1

                        proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                        conn, current_proxy_ip = make_connection(timeout=retry_time)

                        continue
                    else:
                        request_attempts += 1
                        if request_attempts > request_retries:
                            raise ValueError(f"Bad response status on a product API: {response.status}")
                        self.logger.warning(f"Bad response status on a product API: {response.status}, retrying...")
                        wait_with_backoff(request_attempts=request_attempts, backoff_factor=backoff_factor)
                        conn, current_proxy_ip = make_connection(timeout=retry_time)
                        continue
                except Exception as e:
                    self.logger.error(f'Failed to receive data from a product API for product ID {product_id}: {e}')
                    request_attempts += 1
                    if request_attempts > request_retries:
                        self.logger.error("Exceeded maximum number of retries! Exiting parser...")

                        if save_data and data_list:
                            save_data_to(data_list)

                            data_list = []
                            if failed_product_ids:
                                self.logger.warning(f'Failed to parse {len(failed_product_ids)} products.')
                                if save_data:
                                    save_data_to(failed_product_ids, 'failed_product_ids')
                        break
                    wait_with_backoff(request_attempts=request_attempts, backoff_factor=backoff_factor)
                    conn, current_proxy_ip = make_connection()
                    continue
        except Exception as e:
            self.logger.error(f'Error while fetching products: {e}')
            status = 1
        finally:
            if self.proxy_manager and self.shut_down_proxy_scheduler:
                self.logger.debug(f"In {__file__}: Closing proxy_manager scheduler.")
                self.proxy_manager.shutdown_scheduler()
            if conn is not None:
                conn.close()

        if data_list:
            self.logger.info(f'Finished parsing {ind} products.')
            self.logger.info(f'Total products parsed for {datetime.now().strftime("%d/%m/%Y")}: {total_products_count}')
            if save_data:
                file_name = None
                if len(data_list) == 1 and ind <= 1:
                    file_name = str(p_ids[0])
                save_data_to(data_list, file_name)
        else:
            self.logger.warning(f'{product_count if product_count else "Zero"} products parsed!')
        if failed_product_ids:
            self.logger.warning(f'Failed to parse {len(failed_product_ids)} products.')
            if save_data:
                save_data_to(failed_product_ids, 'failed_product_ids')

        end_time = time.time()
        self.logger.info(f"Product parser executing time: {end_time - start_time:.2f} seconds")

        # return total_data_list, failed_product_ids, status
        return status, ind

    def run(self, p_ids: List[int], ind: int = 0) -> Tuple[int, int]:
        """
        Start the product fetching and parsing process.

        Args:
            p_ids (List[int]): List of product IDs to fetch.

        Returns:
            Tuple[List[Dict[str, Any]], List[int], int]:
                A tuple containing status code and last processed index in the list of products.
        """
        self.logger.info("Starting to fetch and parse products")
        try:
            self.logger.info(f"Starting to fetch products from index {ind}.")
            return self.fetch_products(p_ids, ind=ind)
        except Exception as e:
            self.logger.error(f"In {__file__}->main: {e}")
            # return status, ind
            return 1, 0

    def load_ids(self, file_name: str = "", ind: int = 0, run_ids_fetcher: bool = True) -> Optional[List[int]]:
        """
        Load product IDs from a specified file starting from a given index.

        Args:
            file_name (str, optional): Name of the file to load product IDs from. Defaults to "".
            ind (int, optional): Index to start loading from. Defaults to 0.

        Returns:
            Optional[List[int]]: A list of product IDs or None if loading fails.
        """
        product_list = load_last_saved_json(directory=f'{self.data_dir}/{self.product_ids_dir}', file_name=file_name)
        if product_list:
            # return product_list[ind:]
            self.logger.info(f"Loaded {len(product_list)} product IDs for fetching.")
            return product_list
        elif run_ids_fetcher:
            self.logger.info("IDs not found in local storage. Running IdsFetcher.")
            try:
                ids_fetcher = IdsFetcher()
                categories = ids_fetcher.load_categories()
                if categories:
                    product_list = ids_fetcher.fetch_product_ids_by_categories(categories=categories)
                    return product_list
            except Exception as e:
                self.logger.error(f"While running IdsFetcher: {e}")

        self.logger.error(f"No product IDs found in {self.data_dir}/{self.product_ids_dir}. Try running first 'IdsFetcher'")
        return None


if __name__ == "__main__":
    product_fetcher = ProductFetcher()

    parser = argparse.ArgumentParser(description='Processing of product data.')
    parser.add_argument('product_ids', metavar='N', type=int, nargs='*',
                        help='An integer for the product ID to process or the path to the product IDs directory.')
    parser.add_argument('-l', '--load', metavar='FILENAME', type=str, nargs='?',
                        const='product_ids', help='Load the last saved product IDs. Specify a file name to load from data/product_ids.')
    parser.add_argument('-i', '--index', metavar='START_INDEX', type=int, nargs='?',
                        const=0, help='Index in the categories list to start fetching from.')

    args = parser.parse_args()
    product_list: List[int] = []
    if args.load:
        file_name = args.load
        if file_name:
            product_fetcher.logger.info(f"Loading IDs data from file: {file_name}")
        else:
            product_fetcher.logger.info(f"Loading the last saved IDs from: {product_fetcher.data_dir}/product_ids")
        loaded_ids = product_fetcher.load_ids(file_name)
        # loaded_ids = product_fetcher.load_ids(file_name, args.index if args.index else 0)
        if loaded_ids:
            product_list = loaded_ids
    elif args.product_ids:
        product_fetcher.logger.info(f'Parsing product with ID(s): {args.product_ids}')
        product_list = args.product_ids
    else:
        product_fetcher.logger.error("No product IDs provided!")
        product_fetcher.logger.info("Try using -l or --load to load most recent IDs. Or provide product ID(s) to parse specific product(s).")

    if product_list:
        product_fetcher.logger.info(f"Starting to parse products from the input. Data language: {product_fetcher.accept_language.split("-")[1]}")
        try:
            # fetched_data, failed_ids, status = product_fetcher.run(product_list)
            status, ind = product_fetcher.run(product_list, args.index if args.index else 0)
            # Optionally, handle fetched_data and failed_ids as needed
        except Exception as e:
            product_fetcher.logger.error(f"In {sys.argv[0]}->main: {e}")
