import argparse
import configparser
import brotli
import zlib
import logging.config
import json
import time
import uuid
import http.client
from typing import List, Dict, Any, Tuple
from token_manager import TokenManager
from fake_useragent import UserAgent
from save_and_load_data import save_to_file, load_last_saved_json
from proxy_manager import ProxyManager


class IdsFetcher:
    def __init__(self,
                 config_path: str = 'configs/app.conf',
                 logging_path: str = 'configs/logging.conf',
                 offset_limit: int = None,
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
        self.product_ids_dir = self.config.get('storage', 'product_ids_sub_dir')
        self.failed_categories_dir = self.config.get('storage', 'failed_categories_sub_dir')
        self.category_ids_dir = self.config.get('storage', 'category_ids_sub_dir')
        self.proxy_dir = self.config.get('storage', 'proxy_dir')

        self.main_url = self.config.get('urls', 'main_url')
        self.graphql_url = self.config.get('urls', 'graphql_url')

        # Fetching alg parameters
        self.offset_limit = offset_limit if offset_limit else int(self.config.get('ids_fetching', 'offset_limit'))
        self.use_direct_connection = use_direct_connection if use_direct_connection else self.config.getboolean('ids_fetching', 'use_direct_connection')
        self.proxy_timeout = proxy_timeout if proxy_timeout else float(self.config.get('ids_fetching', 'proxy_timeout'))
        self.proxy_manager_timeout = proxy_manager_timeout if proxy_manager_timeout else int(self.config.get('ids_fetching', 'proxy_manager_timeout'))
        self.batch_size = batch_size if batch_size else int(self.config.get('ids_fetching', 'batch_size'))

        # Managers
        self.token_manager = None
        self.proxy_manager = None
        self.auth_token = None

        self.ua = UserAgent()

        self.headers = {
            'Accept': '*/*',
            'Accept-Language': 'ru-RU',
            'apollographql-client-name': 'web-customers',
            'apollographql-client-version': '1.25.2',
            'Authorization': f'Bearer',
            'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=dcdef1759da34ae6894f8629c5d59343',
            'Content-Type': 'application/json',
            'Origin': f'{self.main_url}',
            'Priority': 'u=1, i',
            'Referer': f'{self.main_url}',
            'sec-fetch-site': 'same-site',
            'sentry-trace': str(uuid.uuid4()),
            'User-Agent': self.ua.random,
            'x-iid': str(uuid.uuid4())
        }

        self.payload_json = {
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
        self.query_sort_types = [
            'BY_RELEVANCE_DESC',
            'BY_PRICE_ASC',
            'BY_PRICE_DESC',
            'BY_RATING_DESC',
            'BY_ORDERS_NUMBER_DESC',
            'BY_DATE_ADDED_DESC'
        ]

    def initialize_managers(self, **kwargs):
        if not self.token_manager:
            self.logger.debug("Initializing TokenManager in IdsFetcher")
            self.token_manager = TokenManager(
                url=kwargs.get('url', self.main_url),
                max_retries=kwargs.get('token_retries', 5),
                save_token=kwargs.get('save_token', False),
                save_cookies=False
            )
        if not self.proxy_manager and not self.use_direct_connection:
            self.logger.debug("Initializing ProxyManager in IdsFetcher")
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

    def get_ids_from_json(self, json_data: Dict[str, Any]) -> List[int]:
        """
        Extract product IDs from the given JSON data with thorough field existence checks.

        Args:
            json_data (Dict[str, Any]): The JSON data.

        Returns:
            List[int]: List of product IDs.
        """
        product_ids = []
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

    def get_product_ids_by_category(self,
                                    category_id: int,
                                    amount: int = 0,
                                    page_limit: int = 100,
                                    request_retries: int = 10,
                                    backoff_factor: int = 1,
                                    save_data: bool = True,
                                    save_by_category: bool = False,
                                    ) -> Tuple[List[int], int]:
        """
        Fetch product IDs by category with pagination and retries.

        Args:
            category_id (int): The category ID.
            amount (int): The total amount of products to fetch.
            page_limit (int, optional): The limit of products per page.
            request_retries (int, optional): Number of retries for the request.
            backoff_factor (int, optional): Backoff factor for retries.
            save_data (bool, optional): Whether to save the fetched IDs to a CSV file.

        Returns:
            Tuple[List[int], int]: A tuple containing the list of product IDs and the status code.
        """

        self.initialize_managers()

        if self.auth_token is None:
            self.auth_token = self.token_manager.get_token_instance()
            if self.auth_token is None:
                raise FileNotFoundError("Failed to get authorization token.")

        self.headers['Authorization'] = f'Bearer {self.auth_token}'
        self.headers['User-Agent'] = self.ua.random

        host = self.graphql_url.split('//')[1].split('/')[0]
        endpoint = '/'

        self.payload_json["variables"]["queryInput"]["pagination"]["limit"] = page_limit

        # offset_limit = self.offset_limit
        # use_direct_connection = self.use_direct_connection
        # batch_size = self.batch_size
        proxy_timeout = self.proxy_timeout
        proxy_manager_timeout = self.proxy_manager_timeout

        query_sort_ind = 0
        items_offset = 0
        data_list = []
        prev_data = []
        request_attempts = 0
        done = False
        status = None

        conn = None
        current_proxy_ip = None
        ind = 0
        proxy_ind = 0

        def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
            self.logger.info(f"Server rejected. Attempt number {request_attempts}")
            wait_time = backoff_factor * (2 ** request_attempts)
            self.logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        def make_connection(timeout: float = proxy_timeout if proxy_timeout else 10,
                            pm_timeout: int = proxy_manager_timeout if proxy_manager_timeout else 10,
                            put_to_sleep: bool = False
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
                except:
                    self.logger.warning(f"No proxy connection! Establishing direct connection to {host}")
                    conn = direct_connection()
                    current_proxy_ip = None
            else:
                self.logger.debug(f"Establishing direct connection to {host}")
                conn = direct_connection()
                current_proxy_ip = None
            return conn, current_proxy_ip

        try:
            if proxy_ind % self.batch_size == 0:
                conn, current_proxy_ip = make_connection()

            while not done and request_attempts <= request_retries:
                self.payload_json["variables"]["queryInput"]["categoryId"] = f"{category_id}"
                self.payload_json["variables"]["queryInput"]["pagination"]["offset"] = items_offset
                self.payload_json["variables"]["queryInput"]["sort"] = f"{self.query_sort_types[query_sort_ind]}"

                try:
                    conn.request("POST", endpoint, json.dumps(self.payload_json), headers=self.headers)
                    response = conn.getresponse()
                    status = response.status
                    if response.status == 200:
                        response_data = response.read()
                        content_encoding = response.getheader('Content-Encoding')

                        if content_encoding:
                            response_data = self.decompress_http_response(response_data, content_encoding)
                        decoded_data = response_data.decode('utf-8')

                        if not decoded_data:
                            raise ValueError(
                                "Empty response data from graphql query")

                        json_data = json.loads(decoded_data)

                        # Check for errors in the response
                        if 'errors' in json_data:
                            error_messages = [
                                error.get('message', 'Unknown error') for error in json_data['errors']]
                            error_429 = False
                            for error_message in error_messages:
                                self.logger.warning(f'GraphQL Error: {error_message}')
                                if '429' in error_message:
                                    error_429 = True

                            if error_429:
                                retry_time = int(response.headers.get("Retry-After", 1))
                                self.logger.warning(f"429 (JSON errors): Blocked by the server due to too many requests. Server cool down time: {retry_time}")
                                status = 429

                                proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                                conn, current_proxy_ip = make_connection(timeout=retry_time)

                                request_attempts += 1
                                continue

                        data = self.get_ids_from_json(json_data)
                        if amount == 0:
                            amount = json_data.get("data", {}).get(
                                "makeSearch", {}).get("total")
                        if len(data) > 0:
                            data_list.extend(data)
                        else:
                            done = True
                            amount = json_data.get("data", {}).get(
                                "makeSearch", {}).get("total")

                        self.logger.debug(f'Collected {len(data)} of total {len(data_list)} collected items in category {category_id}')

                        items_offset += min(page_limit, amount - len(data_list))
                        if (len(data_list) >= amount) or (data == prev_data):
                            done = True

                        # If reached the offset limit, try other types of query sorting to extract maximum data
                        if items_offset >= self.offset_limit:
                            if query_sort_ind < len(self.query_sort_types) - 1:
                                items_offset = 0
                                query_sort_ind += 1
                                self.logger.info(f"Reached the API offset limit of 10,000. Switching to sort type {self.query_sort_types[query_sort_ind]}")
                                # add 10000 to prevent stopping (the amount is now irrelevant)
                                amount += self.offset_limit
                            else:
                                done = True

                        prev_data = data
                        request_attempts = 0
                        ind += 1
                        proxy_ind += 1

                    elif response.status == 401:  # authorization failed
                        self.logger.warning(f"{response.status}: Authorization failed during the GraphQL request; retrieving a new token...")
                        # wait_with_backoff(request_attempts, backoff_factor)
                        self.auth_token = self.token_manager.get_token_instance()
                        self.headers['Authorization'] = f'Bearer {self.auth_token}'
                        request_attempts += 1
                        if request_attempts > 1:
                            conn, current_proxy_ip = make_connection()
                        else:
                            conn, current_proxy_ip = make_connection(put_to_sleep=False)

                    elif response.status == 429:  # too many requests
                        retry_time = int(response.headers.get("Retry-After", 1))
                        self.logger.warning(f"429 (JSON errors): Blocked by the server due to too many requests. Server cool down time: {retry_time}")
                        # wait_with_backoff(request_attempts, backoff_factor)

                        proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                        conn, current_proxy_ip = make_connection(timeout=retry_time)

                        request_attempts += 1

                        continue
                    else:
                        request_attempts += 1
                        if request_attempts > request_retries:
                            raise ValueError(f"Bad response status on a GraphQL query: {response.status}")
                        self.logger.warning(f"Bad response status on a GraphQL query: {response.status}, retying...")
                        wait_with_backoff(request_attempts, backoff_factor)
                except Exception as e:
                    self.logger.error(
                        f'Failed to receive data from a GraphQl query: {e}')
                    break
        except Exception as e:
            self.logger.error(f"In get_products_id_by_category: {e}")
        finally:
            if conn is not None:
                conn.close()

        if len(data_list) != 0:
            self.logger.info(f"Finished retrieving category ids. Total collected {
                len(data_list)} out of {amount} in GraphQL in category {category_id}")
            data_list = list(set(data_list))
            self.logger.info(f"Total unique ids: {len(data_list)} in category {category_id}, return status: {status}")
            if save_data:
                save_to_file(data_list, self.product_ids_dir, self.product_ids_dir, separate_folder=False, override_file=False)
                if save_by_category:
                    save_to_file(data_list, f'category_{category_id}_pr_ids', 'products_by_category', separate_folder=False)
        else:
            self.logger.warning(f"No items collected from category {category_id}, return status: {status}")

        return data_list, status

    def fetch_product_ids_by_categories(self,
                                        categories: List[Dict[str, Any]],
                                        save_data: bool = True,
                                        load_most_recent_if_failed: bool = False,
                                        sort_result: bool = False,
                                        **kwargs) -> List[int]:
        """
        Fetch product IDs by categories and optionally save the fetched data.

        Args:
            categories (List[Dict[str, Any]]): List of categories to fetch product IDs from.
            save_data (bool, optional): Whether to save the fetched data to a CSV file.

        Returns:
            List[int]: List of fetched product IDs.
        """
        start_time = time.time()

        self.initialize_managers(**kwargs)
        self.auth_token = self.token_manager.get_token_instance()
        p_ids = []
        try:
            if self.auth_token is not None:
                failed_categories = []
                for category in categories:
                    category_ids, status = self.get_product_ids_by_category(category_id=category['id'], amount=category['productAmount'], save_data=save_data)
                    if len(category_ids) > 0:
                        p_ids.extend(category_ids)
                    if status != 200:
                        failed_categories.append({"id": category['id'], "productAmount": category['productAmount'], "status": status})

                self.logger.info(f"Total {len(p_ids)} ids fetched.")
                p_ids = list(set(p_ids))
                self.logger.info(f"Total unique ids fetched: {len(p_ids)}")
                self.logger.info(f'Total number of failed categories: {
                    len(failed_categories)}')
                if sort_result:
                    p_ids = sorted(p_ids)
                if save_data:
                    if p_ids:
                        save_to_file(p_ids, f"{self.product_ids_dir}_final", self.product_ids_dir, separate_folder=False)
                    if failed_categories:
                        save_to_file(failed_categories, 'failed_categories_ids', self.failed_categories_dir, separate_folder=False)

                if not p_ids and load_most_recent_if_failed:
                    self.logger.warning(f"Could not fetch product IDs from {self.main_url}, loading most recent saved ids.")
                    p_ids = load_last_saved_json(f'{self.data_dir}/{self.product_ids_dir}', 'product_ids')
            else:
                raise FileNotFoundError("Failed to get authorization token.")
        except Exception as e:
            self.logger.error(f"In 'fetch_product_ids_by_category': {e}")
        finally:
            if self.proxy_manager:
                self.proxy_manager.shutdown_scheduler()

        end_time = time.time()
        self.logger.info(f"Product ID's fetching execution time: {end_time - start_time:.2f} seconds")
        return p_ids

    def run(self, categories: List[Dict[str, Any]], **kwargs):
        self.logger.info("Starting to fetch product IDs for the input categories...")
        try:
            return self.fetch_product_ids_by_categories(categories, **kwargs)
        except Exception as e:
            self.logger.error(f"In {__file__}->main: {e}")

    def load_categories(self, file_name: str = "", ind: int = 0) -> List[int]:
        categories = load_last_saved_json(directory=f'{self.data_dir}/{self.category_ids_dir}', file_name=file_name)
        if categories:
            return categories[ind:]
        else:
            self.logger.error(f"No categories found in {self.data_dir}/{self.category_ids_dir}. Try running first 'root_categories.py.' ")
            return None


if __name__ == "__main__":
    id_fetcher = IdsFetcher()

    parser = argparse.ArgumentParser(description='Fetch product IDs by category.')
    parser.add_argument('categories', metavar='CATEGORY_ID', type=int, nargs='*',
                        help='Category IDs or the path to category IDs to fetch product IDs from.')
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save fetched product IDs to file.')
    parser.add_argument('-l', '--load', metavar='FILENAME', type=str, nargs='?',
                        const="", help='Load most recent categories locally stored.')
    parser.add_argument('-o', '--sort', action='store_true',
                        help='Sort the resulting product IDs.')
    parser.add_argument('-i', '--index', metavar='START_INDEX', type=int, nargs='?',
                        const=0, help='Index in the categories list to start fetching from.')
    args = parser.parse_args()

    if args.categories:
        id_fetcher.logger.info("Received categories from a user.")
        categories = [{'id': cid, 'productAmount': 0} for cid in args.categories]
    elif args.load is not None:
        file_name = args.load
        if file_name:
            id_fetcher.logger.info(f"Loading IDs from {file_name}")
        else:
            id_fetcher.logger.info("Loading IDs from most recent category IDs")
        categories = id_fetcher.load_categories(file_name, args.index if args.index else 0)
        id_fetcher.logger.info("Starting to fetch IDs from categories loaded")
    else:
        id_fetcher.logger.error("No categories provided!")
        id_fetcher.logger.info("Try using -l or --load to load most recent categories. Or type category IDs to fetch.")

    if categories:
        try:
            id_fetcher.run(categories, save_data=args.save, load_most_recent_if_failed=False, sort_result=args.sort)
        except Exception as e:
            id_fetcher.logger.error(f"In {__file__}->main: {e}")
