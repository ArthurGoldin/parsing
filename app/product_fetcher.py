import http.client
import time
import json
import logging
import logging.config
import zlib
import brotli
import sys
import re
import argparse
import configparser
import uuid
import os
from fake_useragent import UserAgent
from datetime import datetime

from save_and_load_data import load_last_saved_json, save_to_file
from send_data_to_db import send_message_broker, send_message_redis
from proxy_manager import ProxyManager, ProxyUnavailableError
from token_manager import TokenManager
from ids_fetcher import IdsFetcher
from typing import List, Tuple, Dict, Any, Optional
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
                 init_time: str = None,
                 use_direct_connection: Optional[bool] = None,
                 proxy_timeout: Optional[float] = None,
                 proxy_manager_timeout: Optional[int] = None,
                 batch_size: Optional[int] = None,
                 package_size: Optional[int] = None,
                 backoff_factor: Optional[int] = None,
                 request_retries: Optional[int] = None,
                 config_path: str = config_path,
                 logging_path: str = logging_config_path,) -> None:
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
        self.init_time = init_time if init_time is not None else datetime.now().strftime("%Y%m%d")
        self.id = str(uuid.uuid4())[0:7]
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
        self.graphql_url = self.config.get('urls', 'graphql_url')

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
        self.backoff_factor = backoff_factor if backoff_factor is not None else \
            int(self.config.get('product_fetching', 'conn_time_backoff_factor'))
        self.request_retries = request_retries if request_retries is not None else \
            int(self.config.get('product_fetching', 'connection_retries'))

        # Connection variables
        self.proxy_ind: int = 0
        self.conn: http.client.HTTPSConnection = None
        self.current_proxy_ip: str = None
        self.request_attempts = 0
        self.current_pm_timeout = self.proxy_manager_timeout
        self.status = 0

        self.no_img_ids: List[int] = []

        self.brands_by_category = load_last_saved_json(f"{self.data_dir}/{self.config.get('storage', 'brands_sub_dir')}")

        # Managers
        self.proxy_manager: Optional[ProxyManager] = proxy_manager
        self.shut_down_proxy_scheduler = False if proxy_manager is not None else True
        self.token_manager: Optional[TokenManager] = token_manager
        self.auth_token: Optional[str] = self.token_manager.token if token_manager is not None else None

        self.ua = UserAgent()

        self.headers: Dict[str, str] = {
            'authority': f"{self.product_api_url.split('//')[1].split('/')[0]}",
            'method': 'GET',
            'path': f"{self.product_api_url.split('https://' + self.product_api_url.split('//')[1].split('/')[0])[1]}",
            'scheme': 'https',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': self.accept_language,
            'Authorization': f"Bearer {self.auth_token if self.auth_token is not None else ''}",
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
        self.logger.info(f"use_direct_connection: {self.use_direct_connection}, proxy_manager: {self.proxy_manager}")
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
            self.headers['Authorization'] = f"Bearer {self.auth_token}"

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

    def send_img_obj_to_broker(self, img_url: str, product_id):
        obj_key = f"{product_id}_{img_url.split('/')[-2]}_{img_url.split('/')[-1]}"
        img_data = {
            "url": img_url,
            "image_category": 'product',
            "object_key": obj_key
        }
        try:
            send_message_broker(img_data, host=self.broker_host, port=self.broker_port, queue_name="products_images")
        except Exception as e:
            self.logger.error(f"Failed to send image data to broker 'products_images': {e}")

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
                    self.logger.error(f"Failed to retrieve an image URL: {e}")
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

            # Send image to broker
            if len(payload.get('photos', {})) > 0:
                img_url = get_image_url(payload.get('photos', {})[0].get('photo', {}))
                if send_img_to_broker:
                    self.send_img_obj_to_broker(img_url, payload.get('id'))
            else:
                img_url = ""
                self.no_img_ids.append(payload.get('id'))

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
                'url': f"{self.main_url}/product/{payload.get('id')}",
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
                    # 'fullPrice': sku.get('purchasePrice')
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

    def wait_with_backoff(self, backoff_factor: float = None, request_attempts: int = None, msg: str = "Connection error") -> None:
        """
        Wait for a certain period based on the backoff factor and the number of request attempts.

        Args:
            request_attempts (int): The current number of request attempts.
            backoff_factor (float): The backoff factor to calculate wait time.
        """
        if backoff_factor is None:
            backoff_factor = self.backoff_factor
        if request_attempts is None:
            request_attempts = self.request_attempts
        self.logger.warning(f"{msg}. Attempt number {request_attempts}")
        wait_time = min(backoff_factor * (2 ** request_attempts), 3600)
        self.logger.info(f"Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    def make_connection(self,
                        host: str,
                        timeout: float = 2.5,
                        pm_timeout: int = 10,
                        put_to_sleep: bool = True
                        ) -> Tuple[http.client.HTTPSConnection, Optional[str]]:
        """
        Establish a new HTTP connection, optionally using a proxy.

        Args:
            timeout (float, optional): Timeout for the connection. Defaults to proxy_timeout or 10.
            pm_timeout (int, optional): Timeout for the proxy manager. Defaults to proxy_manager_timeout or 10.
            put_to_sleep (bool, optional): Whether to put the proxy to sleep after use. Defaults to True.

        Returns:
            Tuple[http.client.HTTPSConnection, Optional[str]]: The HTTPS connection and the proxy IP if used.
        """

        def direct_connection() -> http.client.HTTPSConnection:
            if self.request_attempts > 0:
                self.wait_with_backoff(self.request_attempts, self.backoff_factor, msg="Direct connection failed")
            return http.client.HTTPSConnection(host)

        if not self.use_direct_connection:
            if self.conn is not None:  # Close the previous connection before establishing a new one
                self.logger.debug(f"Closing connection for batch {self.proxy_ind // self.batch_size}")
                self.conn.close()
                if self.current_proxy_ip and put_to_sleep:
                    self.logger.debug(f"Setting to sleep proxy {self.current_proxy_ip}")
                    self.proxy_manager.sleep_proxy(self.current_proxy_ip, timeout)
            self.logger.debug(f"Establishing connection for batch {self.proxy_ind // self.batch_size + 1}")
            self.headers['User-Agent'] = self.ua.random
            try:
                self.logger.debug(f"Picking a proxy and establishing a connection")
                self.conn, self.current_proxy_ip = self.proxy_manager.make_connection(host, pm_timeout)
                # return self.conn, self.current_proxy_ip
            except ProxyUnavailableError as e:
                self.logger.error(f"Proxy error: {e}")
                if "expired" in str(e).lower():
                    self.status = 30
                    self.logger.error("Proxies have expired.")  # Proxies are expired
                else:
                    self.status = 31  # Proxies are unavailable
                    self.logger.error("Proxies are unavailable.")
                self.conn = None
                self.current_proxy_ip = None
            except Exception:
                self.logger.warning("No proxy connection!")
                self.conn = None
                self.current_proxy_ip = None
                self.status = 32  # Unknown proxy error
                # Attempting direct connection if proxy fails
        else:
            self.logger.debug(f"Establishing direct connection to {host}")
            self.conn = direct_connection()
        # return self.conn, self.current_proxy_ip

    def check_for_json_errors(self, json_data: Dict[str, Any]) -> List[int]:
        errors = []
        if 'errors' in json_data:
            try:
                error_messages = [error.get('message', 'Unknown error') for error in json_data['errors']]
                for error_message in error_messages:
                    self.logger.warning(f"Response JSON API Error: {error_message}")
                    if '429' in error_message:
                        errors.append(429)
                    if '401' in error_message:
                        errors.append(401)
                errors = list(set(errors))
            except Exception as e:
                self.logger.error(f"Failed to check for JSON response errors: {e}")
        if len(errors) > 0:
            self.logger.warning(f"JSON response errors: {errors}")
        return errors

    def process_errors(self,
                       response: http.client.HTTPResponse,
                       err_code: Optional[List[int]],
                       host: str
                       ) -> bool:
        # if multiple errors, process the heights error code
        if isinstance(err_code, list):
            err_code = err_code[-1]

        request_type = ""
        if 'api' in host:
            request_type = "API"
        elif 'graphql' in host:
            request_type = "GraphQL"

        try:
            if err_code == 401:
                self.logger.warning(f"{response.status}: Authorization failed during a product {request_type} request; retrieving a new token...")
                self.auth_token = self.token_manager.get_token_instance()
                self.headers['Authorization'] = f"Bearer {self.auth_token}"
                if self.request_attempts > 1:
                    self.make_connection(host, pm_timeout=self.current_pm_timeout)
                else:
                    self.make_connection(host, pm_timeout=self.current_pm_timeout, put_to_sleep=False)
            elif err_code == 429:
                retry_time = int(response.headers.get("Retry-After", 1))
                self.logger.warning(f"429: Blocked by the server due to too many {request_type} requests. Server cool down time: {retry_time}")
                self.current_pm_timeout = max(retry_time, self.current_pm_timeout)
                self.make_connection(host, pm_timeout=self.current_pm_timeout, timeout=retry_time)
            else:
                msg = f"Bad status on product {request_type} response: {response.status}"
                if self.request_attempts > self.request_retries:
                    raise ValueError(msg)
                self.logger.warning(f"{msg}, retrying...")
                self.wait_with_backoff(msg=msg)
                self.make_connection(host, pm_timeout=self.current_pm_timeout, timeout=retry_time)
            return True
        except Exception as e:
            self.logger.error(f"Failed to process {request_type} response errors: {e}")
            return False
        finally:
            self.request_attempts += 1

    def process_response(self, response: http.client.HTTPResponse, host: str) -> Tuple[Dict[str, Any], List[int]]:
        if response.status != 200:
            # self.logger.warning(f"Bad status on product API response: {response.status}")
            self.process_errors(response, response.status, host)
            return None, [response.status]

        response_data = response.read()
        content_encoding = response.getheader('Content-Encoding')
        if content_encoding:
            response_data = self.decompress_http_response(response_data, content_encoding)
        decoded_data = response_data.decode('utf-8')

        if not decoded_data:
            raise ValueError("Empty response data from product API")

        json_data = json.loads(decoded_data)
        json_errors = self.check_for_json_errors(json_data)
        if len(json_errors) > 0:
            self.process_errors(response, json_errors, host)
            return json_data, json_errors

        return json_data, []

    def fetch_products(self,
                       p_ids: List[int],
                       ind: int = 0,
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

        host = self.product_api_url.split("//")[1].split('/')[0]
        endpoint_base = self.product_api_url.split(f"https://{host}")[1]

        self.initialize_managers()

        self.headers["User-Agent"] = self.ua.random

        data_list: List[Dict[str, Any]] = []
        # total_data_list: List[Dict[str, Any]] = []
        total_products_count = ind
        product_count = 0
        failed_product_ids: List[int] = []
        self.request_attempts = 0
        self.status = 0
        self.proxy_ind = ind
        self.current_pm_timeout = self.proxy_manager_timeout

        def save_data_to(data_list, file_name: Optional[str] = None):
            if save_data:
                data_to_save = {
                    'platform': 'UZUM',
                    'date': self.init_time,
                    'data': data_list
                }
                if file_name is None:
                    file_name = f"{max(0, total_products_count - self.package_size)}-{total_products_count}"
                save_to_file(data_to_save,
                             file_name,
                             f"{self.products_dir}/{datetime.now().strftime('%Y%m%d')}", override_file=True)

        self.logger.info(f"Total products to parse {len(p_ids)}. Parsing...")
        try:
            while ind < len(p_ids):
                if self.request_attempts > self.request_retries:
                    self.logger.error(f"Exceeded max number of {self.request_retries} retries!")
                    break
                try:
                    if self.proxy_ind % self.batch_size == 0:
                        self.make_connection(host, pm_timeout=self.current_pm_timeout)
                    if self.conn is None:
                        raise ConnectionError("Failed to establish a connection to the server for an API request.")

                    product_id = p_ids[ind]
                    endpoint = f"{endpoint_base}{product_id}"
                    self.headers['path'] = f"{endpoint}"

                    self.conn.request("GET", endpoint, headers=self.headers)
                    response = self.conn.getresponse()

                    json_data, response_errors = self.process_response(response, host)
                    if response_errors:
                        if json_data is not None:
                            self.logger.warning(f"Saving errors in JSON data for product ID {product_id}")
                            save_data_to(json_data, f"response_error_{product_id}")
                        continue

                    if json_data is None:
                        self.logger.warning(f"Failed to receive data from a product API response for product ID {product_id}, but no errors were found.")
                        failed_product_ids.append(product_id)
                    else:
                        data, errors = self.parse_product(json_data, send_to_db)
                        if data:
                            data_list.append(data)
                            total_products_count += 1
                            product_count += 1
                        else:
                            self.logger.warning(f"Failed to parse data from JSON for product ID {product_id}: {errors}")
                            failed_product_ids.append(product_id)

                    self.request_attempts = 0
                    self.current_pm_timeout = self.proxy_manager_timeout
                    self.proxy_ind += 1
                    ind += 1

                    if product_count % self.batch_size == 0:
                        self.logger.debug(f"Processed {ind} products.")
                        self.logger.debug(f"Fetched {product_count} products.")
                    if len(data_list) % self.package_size == 0:
                        if data_list and save_data:
                            save_data_to(data_list)
                        if send_to_db and data_list:
                            data_to_send = {
                                'platform': 'UZUM',
                                'date': self.init_time,
                                'data': [data_list] if len(data_list) == 1 else data_list
                            }
                            try:
                                send_message_broker(data_to_send, host=self.broker_host, port=self.broker_port)
                            except Exception as e:
                                self.logger.error(f"Failed to send to Broker: {e}")
                        data_list = []
                        self.logger.debug(f"Processed {ind} products.")

                except Exception as e:
                    self.logger.error(f"Failed to receive data from an API for product ID {p_ids[ind]}: {e}")
                    if self.status >= 30:  # Proxy error
                        break
                    self.request_attempts += 1
                    if self.request_attempts > self.request_retries:
                        self.logger.error(f"Exceeded max number of {self.request_retries} retries!")
                        break
                    self.wait_with_backoff()
                    self.make_connection(host, pm_timeout=self.current_pm_timeout)
                    continue
        except Exception as e:
            self.logger.error(f"Error while fetching products: {e}")
            self.status = 1
        finally:
            if self.proxy_manager and self.shut_down_proxy_scheduler:
                self.logger.debug(f"In {__file__}: Closing proxy_manager scheduler.")
                self.proxy_manager.shutdown_scheduler()
            if self.conn is not None:
                self.conn.close()

        if data_list:
            self.logger.info(f"Finished processing {ind} products.")
            self.logger.info(f"Total products processed for {datetime.now().strftime('%d/%m/%Y')}: {total_products_count}")
            if send_to_db:
                data_to_send = {
                    'platform': 'UZUM',
                    'date': self.init_time,
                    'data': [data_list] if len(data_list) == 1 else data_list
                }
                # Optionally, send data to DB or other services
                try:
                    send_message_broker(data_to_send, host=self.broker_host, port=self.broker_port)
                except Exception as e:
                    self.logger.error(f"Failed to send to Broker: {e}")
            if save_data:
                file_name = None
                if len(data_list) == 1 and ind <= 1:
                    file_name = str(p_ids[0])
                save_data_to(data_list, file_name)
        else:
            self.logger.warning(f"{product_count if product_count else 'Zero'} products parsed!")
        if failed_product_ids:
            self.logger.warning(f"Failed to parse {len(failed_product_ids)} products.")
            if save_data:
                save_data_to(failed_product_ids, 'failed_product_ids')
        if ind < len(p_ids) and self.status <= 20:
            self.logger.warning(f"Total products processed for current try is {ind} out of {len(p_ids)}")
            self.status = 20

        # return total_data_list, failed_product_ids, status
        return ind

    def fetch_imgs_with_graphql(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch product images using a GraphQL query.

        Args:
            product_id (int): The ID of the product to fetch images for.

        Returns:
            Optional[List[Dict[str, Any]]]: A list of photos with their URLs, or None if an error occurred.
        """

        graphql_query = """
        query ProductPhotos($productId: Int!) {
            productPage(id: $productId) {
                product {
                    photos {
                        key
                        link(trans: PRODUCT_720) {
                            high
                            low
                        }
                    }
                }
            }
        }
        """

        host = self.graphql_url.split('//')[1].split('/')[0]
        endpoint = '/'

        headers: Dict[str, str] = {
            'Accept': '*/*',
            'Accept-Language': 'ru-RU',
            'apollographql-client-name': 'web-customers',
            'apollographql-client-version': '1.25.2',
            'Authorization': f"Bearer {self.auth_token if self.auth_token is not None else ''}",
            'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=dcdef1759da34ae6894f8629c5d59343',
            'Content-Type': 'application/json',
            'Origin': self.main_url,
            'Priority': 'u=1, i',
            'Referer': self.main_url,
            'sec-fetch-site': 'same-site',
            'sentry-trace': str(uuid.uuid4()),
            'User-Agent': self.ua.random,
            'x-iid': str(uuid.uuid4())
        }
        ind = 0
        self.request_attempts = 0
        count = 0
        self.current_pm_timeout = self.proxy_manager_timeout
        self.proxy_ind = 0
        failed_ids = []
        try:
            while ind < len(self.no_img_ids):
                if self.request_attempts > self.request_retries:
                    self.logger.error(f"Exceeded max number of {self.request_retries} retries during fetching GraphQL image URLs!")
                    break

                if self.proxy_ind % self.batch_size == 0:
                    self.make_connection(host, pm_timeout=self.current_pm_timeout)
                if self.conn is None:
                    raise ConnectionError("Failed to establish a connection to the server for a GraphQL query.")

                product_id = self.no_img_ids[ind]
                variables = {
                    "productId": product_id
                }

                payload = json.dumps({
                    "query": graphql_query,
                    "variables": variables
                })

                self.conn.request("POST", endpoint, body=payload, headers=headers)
                response = self.conn.getresponse()

                json_data, response_errors = self.process_response(response, host)
                if response_errors:
                    continue

                # Parse the response
                photos = json_data.get("data", {}).get("productPage", {}).get("product", {}).get("photos", [])

                if not photos:
                    self.logger.warning(f"No image URLs found for product ID {product_id}.")
                    failed_ids.append(product_id)

                elif len(photos) > 0:
                    img_url = photos[0].get("link", {}).get("low")
                    if img_url is None:
                        img_url = photos[0].get("link", {}).get("high")
                    if img_url is not None:
                        self.send_img_obj_to_broker(img_url, product_id)
                    else:
                        self.logger.warning(f"No image URL found for product ID {product_id}.")
                    count += 1

                ind += 1
                self.proxy_ind += 1
                self.current_pm_timeout = self.proxy_manager_timeout

        except Exception as e:
            self.logger.error(f"Error during GraphQL request for product ID {self.no_img_ids[ind]}: {e}")
            return None
        finally:
            if self.conn:
                self.conn.close()
        if count > 0:
            self.logger.info(f"Successfully fetched {count} image URLs of total {len(self.no_img_ids)} products with GraphQL queries.")
        else:
            self.logger.warning(f"Failed to fetch image URLs for {len(self.no_img_ids)} products with GraphQL queries.")
        if len(failed_ids > 0):
            self.logger.info(f"Saving failed image IDs to file.")
            save_to_file(failed_ids, "failed_img_ids", f"{self.data_dir}/{self.product_ids_dir}", override_file=True)

    def load_ids(self, file_name: str = "", ind: int = 0, run_ids_fetcher: bool = True) -> Optional[Tuple[List[int], int]]:
        """
        Load product IDs from a specified file starting from a given index.

        Args:
            file_name (str, optional): Name of the file to load product IDs from. Defaults to "".
            ind (int, optional): Index to start loading from. Defaults to 0.

        Returns:
            Optional[List[int]]: A list of product IDs or None if loading fails.
            Status: 0 if success
        """
        product_list = load_last_saved_json(directory=f"{self.data_dir}/{self.product_ids_dir}", file_name=file_name)
        if product_list:
            # return product_list[ind:]
            self.logger.info(f"Loaded {len(product_list)} product IDs for fetching.")
            return product_list, 0
        elif run_ids_fetcher:
            self.logger.info("IDs not found in local storage. Running IdsFetcher.")
            try:
                ids_fetcher = IdsFetcher(proxy_manager=self.proxy_manager, token_manager=self.token_manager, init_time=self.init_time)
                categories = ids_fetcher.load_categories()
                if categories:
                    self.logger.debug(f"Categories loaded by IdsFetcher.")
                    product_list, status = ids_fetcher.fetch_product_ids_by_categories(categories=categories)
                    return product_list, status
                else:
                    self.logger.error(f"Failed to load categories for product parsing.")
            except Exception as e:
                self.logger.error(f"While running IdsFetcher: {e}")

        self.logger.error(f"No product IDs found in {self.data_dir}/{self.product_ids_dir}. Try running first 'IdsFetcher'")
        return None

    def send_status_to_redis(self, current_status: str, total_products: int, processed_products: int = 0, time: float = 0) -> None:
        error_message = ""
        if self.status == 1:
            error_message = "Unknown error"
        elif self.status == 20:
            error_message = "Server error"
        elif self.status == 30:
            error_message = "Proxies are expired"
        elif self.status == 31:
            error_message = "Proxies are unavailable"
        elif self.status == 32:
            error_message = "Unknown proxy error"
        message = {
            "parsing_id": self.id,
            "parsing_date": self.init_time,
            "status": current_status,
            "error_message": error_message,
            "total_products": total_products,
            "processed": processed_products,
            "time_elapsed": f"{time} seconds"
        }
        if send_message_redis("parsing_status", json.dumps(message)):
            self.logger.info("Status message successfully sent to Redis")
        else:
            self.logger.error("Failed to send status message to Redis!")

    def run(self, p_ids: List[int] = [], ind: int = 0, retries: int = 5, save_data: bool = False, send_data=True) -> Tuple[int, int]:
        """
        Start the product fetching and parsing process.

        Args:
            p_ids (List[int]): List of product IDs to fetch.

        Returns:
            Tuple[FetcherStatus, int]:
                - FetcherStatus: Enum indicating the final status.
                - int: Last processed index in the product list.
        """
        self.logger.info("Starting to fetch and parse products")
        start_time = time.time()

        if p_ids == []:
            p_ids, load_status = self.load_ids()
            if p_ids is None or load_status != 0:
                raise ValueError("No product IDs found!")
        if send_data:
            self.logger.info(f"Sending status to redis")

            if self.status == 0:
                current_status = "process"
            else:
                current_status = "failed"
            self.send_status_to_redis(current_status, len(p_ids))

        attempt = 0
        while attempt < retries and self.status < 30:
            try:
                self.logger.info(f"Attempt {attempt}: starting to fetch products from index {ind}.")
                attempt += 1
                ind = self.fetch_products(p_ids, ind=ind, save_data=save_data, send_to_db=send_data)
                if self.status == 0:
                    self.logger.info(f"Successfully fetched all products.")
                    break
                elif self.status >= 30:
                    self.logger.error(f"Closing product fetcher due to proxy error.")
                    break
                else:
                    self.logger.warning(f"Failed tp finish fetching all products. Return status: {self.status}")
                    self.logger.warning(f"Failed to fetch {len(p_ids[ind:])} of {len(p_ids)} products.")
                    if attempt < retries:
                        self.wait_with_backoff(backoff_factor=1, request_attempts=attempt, msg="Failed to fetch all products.")
                        self.logger.info(f"Retrying: attempt number {attempt} of {retries}...")
                    else:
                        self.logger.error(f"Failed to fetch all products after {retries} attempts.")
            except Exception as e:
                self.logger.error(f"In {__file__}->main: {e}")
                self.status = 1
        # Add code for a GraphQL query
        if self.status == 0 and len(self.no_img_ids) > 0 and send_data:
            self.logger.info(f"Products without image URLs count: {len(self.no_img_ids)} of total {ind} products")
            self.logger.info("Starting to fetch using GraphQL queries...")
            self.fetch_imgs_with_graphql()

        end_time = time.time()
        self.logger.info(f"Product parser executing time: {end_time - start_time:.2f} seconds")
        if send_data:
            if self.status == 0:
                current_status = "completed"
            else:
                current_status = "failed"
            self.send_status_to_redis(current_status, len(p_ids), ind, (end_time - start_time))

        return self.status, ind

    def get_ids_from_category(self, category_id: int) -> Tuple[List[int], int]:
        """
        Fetch product IDs from the given category ID.

        Args:
            category_id (int): The ID of the category to fetch product IDs from.

        Returns:
            List[int]: A list of product IDs fetched from the specified category. If an error occurs, an empty list is returned.
        """
        try:
            self.logger.info(f"Initiating IdsFetcher to fetch product IDs from category {category_id}")
            ids_fetcher = IdsFetcher(proxy_manager=self.proxy_manager, token_manager=self.token_manager, init_time=self.init_time)
            return ids_fetcher.fetch_product_ids_by_categories(category_id, save_data=False)
        except Exception as e:
            self.logger.error(f"While fetching product IDs from category {category_id}: {e}")
            return [], 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Processing of product data.')
    parser.add_argument('product_ids', metavar='N', type=int, nargs='*',
                        help='An integer for the product ID to process or the path to the product IDs directory.')
    parser.add_argument('-l', '--load', metavar='FILENAME', type=str, nargs='?',
                        const='product_ids', help='Load the last saved product IDs. Specify a file name to load from data/product_ids.')
    parser.add_argument('-c', '--categories', metavar='CATEGORY', type=int, nargs='*', help='Category(s) ID(s) to fetch product IDs from.')
    parser.add_argument('-s', '--save', action='store_true', help='Save data to local storage.')
    parser.add_argument('-d', '--disableBroker', action='store_false', help='Define whether to send data to broker.')
    parser.add_argument('-i', '--index', metavar='START_INDEX', type=int, nargs='?',
                        const=0, help='Index in the categories list to start fetching from.')

    product_fetcher = ProductFetcher(use_direct_connection = True)
    product_fetcher.initialize_managers()

    args = parser.parse_args()
    product_list: List[int] = []
    if args.load:
        file_name = args.load
        if file_name:
            product_fetcher.logger.info(f"Loading IDs data from file: {file_name}")
        else:
            product_fetcher.logger.info(f"Loading the last saved IDs from: {product_fetcher.data_dir}/product_ids")
        loaded_ids, status = product_fetcher.load_ids(file_name)
        if status != 30:
            product_fetcher.status = status
        # loaded_ids = product_fetcher.load_ids(file_name, args.index if args.index else 0)
        if loaded_ids:
            product_list = loaded_ids
    elif args.categories:
        product_fetcher.logger.info(f"Fetching product IDs from category(s) {args.categories}")
        product_list, status = product_fetcher.get_ids_from_category(args.categories)
        if status >= 30:
            product_fetcher.status = status
    elif args.product_ids:
        product_fetcher.logger.info(f"Parsing product with ID(s): {args.product_ids}")
        product_list = args.product_ids
    else:
        product_fetcher.logger.error("No product IDs provided!")
        product_fetcher.logger.info("Try using -l or --load to load most recent IDs. Or provide product ID(s) to parse specific product(s).")

    if args.save:
        product_fetcher.logger.info(f"Data will be stored to {product_fetcher.data_dir}/{product_fetcher.products_dir}.")
    else:
        product_fetcher.logger.info("Data storage is disabled.")
    if args.disableBroker:
        product_fetcher.logger.info(f"Sending data to broker is enabled")
    else:
        product_fetcher.logger.info("Sending data to broker is disabled.")

    if product_list:
        product_fetcher.logger.info(f"Starting to parse products from the input. Data language: {product_fetcher.accept_language.split('-')[1]}")
        try:
            # fetched_data, failed_ids, status = product_fetcher.run(product_list)
            status, ind = product_fetcher.run(product_list, args.index if args.index else 0, save_data=args.save, send_data=args.disableBroker)
            # Optionally, handle fetched_data and failed_ids as needed
        except Exception as e:
            product_fetcher.logger.error(f"In {sys.argv[0]}->main: {e}")
