import argparse
import configparser
import brotli
import zlib
import logging.config
import json
import time
import uuid
import http.client
import os
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from token_manager import TokenManager
from fake_useragent import UserAgent
from save_and_load_data import save_to_file, load_last_saved_json
from proxy_manager import ProxyManager, ProxyUnavailableError
from root_categories import get_root_categories, find_leaf_categories

current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')


class IdsFetcher:
    """
    A class to fetch product IDs from various categories using a GraphQL API.

    Attributes:
        config (configparser.ConfigParser): Configuration parser.
        logger (logging.Logger): Logger instance.
        data_dir (str): Directory for storing data.
        product_ids_dir (str): Sub-directory for product IDs.
        failed_categories_dir (str): Sub-directory for failed categories.
        category_ids_dir (str): Sub-directory for category IDs.
        proxy_dir (str): Directory for proxy configurations.
        main_url (str): Main URL of the platform.
        graphql_url (str): GraphQL API URL for fetching product IDs.
        offset_limit (int): Maximum offset limit for pagination.
        use_direct_connection (bool): Flag to use direct connection without proxies.
        proxy_timeout (float): Timeout for proxy connections.
        proxy_manager_timeout (int): Timeout for the proxy manager.
        batch_size (int): Number of requests to batch.
        token_manager (Optional[TokenManager]): Manager for handling tokens.
        proxy_manager (Optional[ProxyManager]): Manager for handling proxies.
        auth_token (Optional[str]): Authorization token.
        ua (UserAgent): User agent generator.
        headers (Dict[str, str]): HTTP headers for requests.
        payload_json (Dict[str, Any]): Payload for GraphQL queries.
        query_sort_types (List[str]): List of sorting types for queries.
    """

    def __init__(self,
                 proxy_manager: Optional[ProxyManager] = None,
                 token_manager: Optional[TokenManager] = None,
                 init_time: str = None,
                 offset_limit: Optional[int] = None,
                 use_direct_connection: Optional[bool] = None,
                 proxy_timeout: Optional[float] = None,
                 proxy_manager_timeout: Optional[int] = None,
                 batch_size: Optional[int] = None,
                 config_path: str = config_path,
                 logging_path: str = logging_config_path,) -> None:
        """
        Initialize the IdsFetcher with configuration and logging.

        Args:
            config_path (str, optional): Path to the configuration file. Defaults to 'configs/app.conf'.
            logging_path (str, optional): Path to the logging configuration file. Defaults to 'configs/logging.conf'.
            offset_limit (Optional[int], optional): Maximum offset limit for pagination. Defaults to None.
            use_direct_connection (Optional[bool], optional): Whether to use direct connection without proxies. Defaults to None.
            proxy_timeout (Optional[float], optional): Timeout for proxy connections. Defaults to None.
            proxy_manager_timeout (Optional[int], optional): Timeout for the proxy manager. Defaults to None.
            batch_size (Optional[int], optional): Number of requests to batch. Defaults to None.
        """

        self.init_time = init_time if init_time is not None else datetime.now().strftime("%Y%m%d")
        # Configure logging
        try:
            logging.config.fileConfig(logging_path)
            self.logger = logging.getLogger('ids_fetcher')
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger()
            self.logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

        # Read configuration
        self.config = configparser.ConfigParser()
        self.config.read(config_path)

        # Initialize attributes
        # self.data_dir = self.config.get('storage', 'data_directory')
        self.data_dir = os.path.join(current_dir, self.config.get('storage', 'data_directory'))
        self.product_ids_dir = self.config.get('storage', 'product_ids_sub_dir')
        self.failed_categories_dir = self.config.get('storage', 'failed_categories_sub_dir')
        self.category_ids_dir = self.config.get('storage', 'category_ids_sub_dir')
        self.proxy_dir = self.config.get('storage', 'proxy_dir')

        self.main_url = self.config.get('urls', 'main_url')
        self.graphql_url = self.config.get('urls', 'graphql_url')

        # Fetching algorithm parameters
        self.offset_limit = offset_limit if offset_limit is not None else int(self.config.get('ids_fetching', 'offset_limit'))
        self.use_direct_connection = use_direct_connection if use_direct_connection is not None else \
            self.config.getboolean('ids_fetching', 'use_direct_connection')
        self.proxy_timeout = proxy_timeout if proxy_timeout is not None else float(self.config.get('ids_fetching', 'proxy_timeout'))
        self.proxy_manager_timeout = proxy_manager_timeout if proxy_manager_timeout is not None else int(self.config.get('ids_fetching', 'proxy_manager_timeout'))
        self.batch_size = batch_size if batch_size is not None else int(self.config.get('ids_fetching', 'batch_size'))

        self.cumulative_save = self.config.getboolean('ids_fetching', 'cumulative_save')

        # Connection variables
        self.conn = None
        self.current_proxy_ip = None
        self.request_counter = 0  # Total number of requests
        self.proxy_ind = 0
        self.request_attempts = 0
        self.current_pm_timeout = self.proxy_manager_timeout
        self.status = 0

        # Managers
        self.proxy_manager: Optional[ProxyManager] = proxy_manager
        self.shut_down_proxy_scheduler = False if proxy_manager is not None else True
        self.token_manager: Optional[TokenManager] = token_manager
        self.auth_token: Optional[str] = self.token_manager.token if token_manager is not None else None

        self.ua = UserAgent()

        self.headers: Dict[str, str] = {
            'Accept': '*/*',
            'Accept-Language': 'ru-RU',
            'apollographql-client-name': 'web-customers',
            'apollographql-client-version': '1.25.2',
            'Authorization': f'Bearer {self.auth_token if self.auth_token is not None else ""}',
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

        self.payload_json: Dict[str, Any] = {
            "operationName": "getMakeSearch",
            "variables": {
                "queryInput": {
                    "categoryId": "0",
                    "showAdultContent": "TRUE",
                    "filters": [],
                    "sort": "BY_RELEVANCE_DESC",
                    "pagination": {
                        "offset": 0,
                        "limit": 100
                    },
                    "correctQuery": True,
                    "getFastCategories": True,
                    "fastCategoriesLevelOffset": 0,
                    "getPromotionItems": False
                }
            },
            "query": """
            query getMakeSearch($queryInput: MakeSearchQueryInput!) {
                makeSearch(query: $queryInput) {
                    category {
                        id
                        title
                    }
                    items {
                        catalogCard {
                            ...SkuGroupCardFragment
                        }
                    }
                    total
                }
            }
            fragment SkuGroupCardFragment on SkuGroupCard {
                ...DefaultCardFragment
            }
            fragment DefaultCardFragment on CatalogCard {
                productId
            }
            """
        }

        self.query_sort_types: List[str] = [
            'BY_RELEVANCE_DESC',
            'BY_PRICE_ASC',
            'BY_PRICE_DESC',
            'BY_RATING_DESC',
            'BY_ORDERS_NUMBER_DESC',
            'BY_DATE_ADDED_DESC'
        ]

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

    def get_ids_from_json(self, json_data: Dict[str, Any]) -> List[int]:
        """
        Extract product IDs from the given JSON data with thorough field existence checks.

        Args:
            json_data (Dict[str, Any]): The JSON data.

        Returns:
            List[int]: List of product IDs.
        """
        product_ids: List[int] = []
        data = json_data.get("data")

        if not data:
            self.logger.error("Missing 'data' field in JSON response.")
            return product_ids

        make_search = data.get("makeSearch")
        if not make_search:
            self.logger.error("Missing 'makeSearch' field in 'data'.")
            return product_ids

        items = make_search.get("items")
        if not items or not isinstance(items, list):
            self.logger.error(f"'items' field is not a list. Received type: {type(items)}")
            return product_ids

        for index, item in enumerate(items):
            catalog_card = item.get("catalogCard")
            if isinstance(catalog_card, dict):
                product_id = catalog_card.get("productId")
                if isinstance(product_id, int):
                    product_ids.append(product_id)
                else:
                    self.logger.warning(f"'productId' in 'catalogCard' at index {index} is not an integer. Skipping.")
            else:
                self.logger.warning(f"Invalid 'catalogCard' at index {index}. Skipping.")

        if not product_ids:
            self.logger.info("No product IDs extracted from JSON data.")
        else:
            self.logger.debug(f"Extracted {len(product_ids)} product IDs.")

        return product_ids

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
        wait_time = min(backoff_factor * (2 ** request_attempts), 2 ** 11)
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
                self.logger.debug(f"Closing connection for batch {self.request_counter // self.batch_size}")
                self.conn.close()
                if self.current_proxy_ip and put_to_sleep:
                    self.logger.debug(f"Setting to sleep proxy {self.current_proxy_ip}")
                    self.proxy_manager.sleep_proxy(self.current_proxy_ip, timeout)
                    self.proxy_ind = 0
            self.logger.debug(f"Establishing connection for batch {self.request_counter // self.batch_size + 1}")
            self.headers['User-Agent'] = self.ua.random
            try:
                self.logger.debug(f"Picking a proxy and establishing a connection")
                self.conn, self.current_proxy_ip = self.proxy_manager.make_connection(host, pm_timeout)
                # return self.conn, self.current_proxy_ip
            except ProxyUnavailableError as e:
                self.logger.error(f"Proxy error: {e}")
                if "expired" in str(e).lower():
                    self.status = 30  # Proxies are expired
                else:
                    self.status = 31  # Proxies are unavailable
                self.conn = None
                self.current_proxy_ip = None
            except Exception:
                self.logger.warning("No proxy connection!")
                self.conn = None
                self.current_proxy_ip = None
                self.status = 32  # Unknown proxy error
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
                    self.logger.warning(f'Response JSON Error: {error_message}')
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
        if 'graphql' in host:
            request_type = "GraphQL"

        try:
            if err_code == 401:
                self.logger.warning(f"{response.status}: Authorization failed during a category {request_type} request; retrieving a new token...")
                self.auth_token = self.token_manager.get_token_instance()
                self.headers['Authorization'] = f'Bearer {self.auth_token}'
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
                msg = f"Bad status on category {request_type} response: {response.status}"
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
            self.process_errors(response, response.status, host)
            return None, [response.status]

        response_data = response.read()
        content_encoding = response.getheader('Content-Encoding')
        if content_encoding:
            response_data = self.decompress_http_response(response_data, content_encoding)
        decoded_data = response_data.decode('utf-8')

        if not decoded_data:
            raise ValueError("Empty response data from a category GraphQL request.")

        json_data = json.loads(decoded_data)
        json_errors = self.check_for_json_errors(json_data)
        if len(json_errors) > 0:
            self.process_errors(response, json_errors, host)
            return json_data, json_errors

        return json_data, []

    def get_product_ids_by_category(self,
                                    category_id: int,
                                    amount: int = 0,
                                    page_limit: int = 100,
                                    request_retries: int = 10,
                                    backoff_factor: int = 1,
                                    save_data: bool = True,
                                    save_by_category: bool = False) -> Tuple[List[int], int]:
        """
        Fetch product IDs by category with pagination and retries.

        Args:
            category_id (int): The category ID.
            amount (int, optional): The total amount of products to fetch. Defaults to 0.
            page_limit (int, optional): The limit of products per page. Defaults to 100.
            request_retries (int, optional): Number of retries for the request. Defaults to 10.
            backoff_factor (int, optional): Backoff factor for retries. Defaults to 1.
            save_data (bool, optional): Whether to save the fetched IDs to a file. Defaults to True.
            save_by_category (bool, optional): Whether to save IDs categorized by category. Defaults to False.

        Returns:
            Tuple[List[int], int]: A tuple containing the list of product IDs and the status code.
        """
        self.initialize_managers()

        self.headers['User-Agent'] = self.ua.random

        host = self.graphql_url.split('//')[1].split('/')[0]
        endpoint = '/'

        self.payload_json["variables"]["queryInput"]["pagination"]["limit"] = page_limit

        self.current_pm_timeout = self.proxy_manager_timeout

        query_sort_ind = 0
        items_offset = 0
        data_list: List[int] = []
        prev_data: List[int] = []
        self.request_attempts = 0
        done = False
        self.status = 0

        # conn: Optional[http.client.HTTPSConnection] = None
        # current_proxy_ip: Optional[str] = None
        # ind = 0
        self.proxy_ind = self.request_counter

        try:
            while not done and self.request_attempts <= request_retries:
                if self.proxy_ind % self.batch_size == 0:
                    self.make_connection(host, pm_timeout=self.current_pm_timeout)
                if self.conn is None:
                    raise ConnectionError("Failed to establish a connection to the server")

                self.payload_json["variables"]["queryInput"]["categoryId"] = f"{category_id}"
                self.payload_json["variables"]["queryInput"]["pagination"]["offset"] = items_offset
                self.payload_json["variables"]["queryInput"]["sort"] = self.query_sort_types[query_sort_ind]

                try:
                    self.conn.request("POST", endpoint, json.dumps(self.payload_json), headers=self.headers)
                    response = self.conn.getresponse()

                    json_data, response_errors = self.process_response(response, host)
                    if response_errors:
                        if json_data is not None:
                            continue

                    data = self.get_ids_from_json(json_data)
                    if amount == 0:
                        amount = json_data.get("data", {}).get("makeSearch", {}).get("total", 0)
                    if len(data) > 0:
                        data_list.extend(data)
                    else:
                        done = True
                        amount = json_data.get("data", {}).get("makeSearch", {}).get("total", 0)

                    self.logger.debug(f'Collected {len(data)} of total {len(data_list)} collected items in category {category_id}')

                    items_offset += min(page_limit, amount - len(data_list))
                    if (len(data_list) >= amount) or (data == prev_data):
                        done = True

                    # If reached the offset limit, try other types of query sorting to extract maximum data
                    if items_offset >= self.offset_limit:
                        if query_sort_ind < len(self.query_sort_types) - 1:
                            items_offset = 0
                            query_sort_ind += 1
                            self.logger.info(f"Reached the API offset limit of {self.offset_limit}. Switching to sort type {self.query_sort_types[query_sort_ind]}")
                            # Add offset_limit to prevent stopping (the amount is now irrelevant)
                            amount += self.offset_limit
                        else:
                            done = True

                        prev_data = data
                        self.request_attempts = 0
                        self.current_pm_timeout = self.proxy_manager_timeout
                        # ind += 1
                        self.proxy_ind += 1
                        self.request_counter += 1

                except Exception as e:
                    self.logger.error(f'Failed to receive data from a GraphQL query: {e}')
                    break
        except Exception as e:
            self.logger.error(f"In get_product_ids_by_category: {e}")
        # finally:
        #     if conn is not None:
        #         conn.close()

        if len(data_list) != 0:
            self.logger.info(f"Finished retrieving category ids. Total collected {len(data_list)} out of {amount} in GraphQL in category {category_id}")
            data_list = list(set(data_list))
            self.logger.info(f"Total unique ids: {len(data_list)} in category {category_id}.")
            if save_data:
                if self.cumulative_save:
                    save_to_file(data_list, self.product_ids_dir, self.product_ids_dir, separate_folder=False, override_file=False)
                if save_by_category:
                    save_to_file(data_list, f'category_{category_id}_pr_ids', 'products_by_category', separate_folder=False)
        else:
            self.logger.warning(f"No items collected from category {category_id}.")

        return data_list

    def fetch_product_ids_by_categories(self,
                                        categories: Any,
                                        save_data: bool = True,
                                        load_most_recent_if_failed: bool = False,
                                        sort_result: bool = False,
                                        **kwargs: Any) -> List[int]:
        """
        Fetch product IDs by categories and optionally save the fetched data.

        Args:
            categories (List[Dict[str, Any]]): List of categories to fetch product IDs from.
            save_data (bool, optional): Whether to save the fetched data to a file. Defaults to True.
            load_most_recent_if_failed (bool, optional): Whether to load the most recent saved IDs if fetching fails. Defaults to False.
            sort_result (bool, optional): Whether to sort the resulting product IDs. Defaults to False.

        Keyword Args:
            Any additional keyword arguments.

        Returns:
            List[int]: List of fetched product IDs.
        """
        start_time = time.time()

        def check_input(categories: Any) -> List[Dict[str, Any]]:
            if isinstance(categories, int):
                self.logger.debug("Converting single category ID to list of dictionaries for processing.")
                categories = [{'id': categories, 'productAmount': 0}]
            elif isinstance(categories, list):
                if isinstance(categories[0], int):
                    self.logger.debug("Converting a list of categories ID to list of dictionaries for processing.")
                    categories = [{'id': cid, 'productAmount': 0} for cid in categories]
            return categories

        categories = check_input(categories)

        self.initialize_managers(**kwargs)

        p_ids: List[int] = []
        try:
            if self.auth_token is not None:
                failed_categories: List[Dict[str, Any]] = []
                for category in categories:
                    category_ids = self.get_product_ids_by_category(
                        category_id=category['id'],
                        amount=category.get('productAmount', 0),
                        save_data=save_data
                    )
                    if len(category_ids) > 0:
                        p_ids.extend(category_ids)
                    if self.status != 0:
                        failed_categories.append({
                            "id": category['id'],
                            "productAmount": category.get('productAmount', 0),
                            "status": self.status
                        })
                    if self.status >= 30:
                        self.logger.error(f"Proxy error.")
                        break

                self.logger.info(f"Total {len(p_ids)} ids fetched.")
                p_ids = list(set(p_ids))
                self.logger.info(f"Total unique ids fetched: {len(p_ids)}")
                self.logger.info(f"Total number of failed categories: {len(failed_categories)}")
                if sort_result:
                    p_ids = sorted(p_ids)
                if save_data:
                    if p_ids:
                        self.logger.info(f"Saving ids to {self.product_ids_dir}")
                        save_to_file(p_ids, f"{self.product_ids_dir}{"_final" if self.cumulative_save else ""}", self.product_ids_dir, separate_folder=False, override_file=False)
                    if failed_categories:
                        self.logger.info(f"Saving ids to {self.failed_categories_dir}")
                        save_to_file(failed_categories, 'failed_categories_ids', self.failed_categories_dir, separate_folder=False)

                if not p_ids and load_most_recent_if_failed:
                    self.logger.warning(f"Could not fetch product IDs from {self.main_url}, loading most recent saved ids.")
                    p_ids = load_last_saved_json(f'{self.data_dir}/{self.product_ids_dir}', 'product_ids')
            else:
                raise FileNotFoundError("Failed to get authorization token.")
        except Exception as e:
            self.logger.error(f"In 'fetch_product_ids_by_category': {e}")
        finally:
            if self.proxy_manager and self.shut_down_proxy_scheduler:
                self.logger.debug(f"In {__file__}: Closing proxy_manager scheduler.")
                self.proxy_manager.shutdown_scheduler()
            if self.conn:
                self.logger.debug(f"In {__file__}: Closing connection.")
                self.conn.close()
            if self.current_proxy_ip:
                self.current_proxy_ip = None

        end_time = time.time()
        self.logger.info(f"Product ID's fetching execution time: {end_time - start_time:.2f} seconds")
        if len(p_ids) == 0:
            return None
        return p_ids, self.status

    def run(self, categories: Any, **kwargs: Any) -> List[int]:
        """
        Start the product ID fetching process for the given categories.

        Args:
            categories (List[Dict[str, Any]]): List of categories to fetch product IDs from.

        Keyword Args:
            Any additional keyword arguments.

        Returns:
            List[int]: List of fetched product IDs.
        """
        self.logger.info(f"Starting to fetch product IDs for the input categories. Total categories: {len(categories)}.")
        try:
            return self.fetch_product_ids_by_categories(categories, **kwargs)
        except Exception as e:
            self.logger.error(f"In {__file__}->run: {e}")
            return []

    def load_categories(self, file_name: str = "", ind: int = 0, run_root_categories: bool = True) -> Optional[List[Dict[str, Any]]]:
        """
        Load categories from a specified file starting from a given index.

        Args:
            file_name (str, optional): Name of the file to load categories from. Defaults to "".
            ind (int, optional): Index to start loading from. Defaults to 0.

        Returns:
            Optional[List[Dict[str, Any]]]: A list of categories or None if loading fails.
        """
        categories = load_last_saved_json(directory=f'{self.data_dir}/{self.category_ids_dir}', file_name=file_name)
        if categories:
            return categories[ind:]
        elif run_root_categories:
            self.logger.info("No stored categories found. Running 'root_categories' to fetch categories.")
            # rc, categories = get_all_root_categories()
            rc = get_root_categories()
            categories = find_leaf_categories(rc)
            if categories:
                return categories[ind:]

        self.logger.error(f"No categories found in {self.data_dir}/{self.category_ids_dir}.")
        return None


if __name__ == "__main__":
    id_fetcher = IdsFetcher()

    parser = argparse.ArgumentParser(description='Fetch product IDs by category.')
    parser.add_argument('categories', metavar='CATEGORY_ID', type=int, nargs='*',
                        help='Category IDs to fetch product IDs from.')
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save fetched product IDs to file.')
    parser.add_argument('-l', '--load', metavar='FILENAME', type=str, nargs='?',
                        const="", help='Load most recent categories locally stored.')
    parser.add_argument('-o', '--sort', action='store_true', help='Sort the resulting product IDs.')
    parser.add_argument('-i', '--index', metavar='START_INDEX', type=int, nargs='?',
                        const=0, help='Index in the categories list to start fetching from.')
    args = parser.parse_args()

    categories = None
    if args.categories:
        id_fetcher.logger.info("Received categories from user input.")
        # categories = [{'id': cid, 'productAmount': 0} for cid in args.categories]
        categories = args.categories
    elif args.load is not None:
        file_name = args.load
        if file_name:
            id_fetcher.logger.info(f"Loading categories from {file_name}")
        else:
            id_fetcher.logger.info("Loading categories from most recent category IDs")
        loaded_categories = id_fetcher.load_categories(file_name, args.index if args.index else 0)
        if loaded_categories:
            categories = loaded_categories
            id_fetcher.logger.info("Starting to fetch IDs from loaded categories")
    else:
        id_fetcher.logger.info("No categories provided. Running 'root_categories' to fetch categories.")
        rc = get_root_categories()
        categories = find_leaf_categories(rc)
        ind = args.index if args.index else 0
        categories = categories[ind:]
        # id_fetcher.logger.info("Try using -l or --load to load most recent categories. Or provide category IDs to fetch.")

    if categories:
        try:
            fetched_ids = id_fetcher.run(
                categories,
                save_data=args.save,
                load_most_recent_if_failed=False,
                sort_result=args.sort
            )
            # Optionally, handle fetched_ids as needed
            id_fetcher.logger.info(f"Fetched {len(fetched_ids)} unique product IDs.")
        except Exception as e:
            id_fetcher.logger.error(f"In {__file__}->main: {e}")
