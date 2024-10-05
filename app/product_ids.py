import argparse
import configparser
import brotli
import zlib
import logging.config
import logging
import json
import time
import http.client
import graphql_query_generator
from typing import List, Dict, Any
from token_manager import TokenManager
from fake_useragent import UserAgent
from typing import List, Tuple, Dict, Any
from save_and_load_data import save_to_file, load_last_saved_json
from proxy_manager import ProxyManager

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
product_ids_dir = config.get('storage', 'product_ids_sub_dir')
failed_categories_dir = config.get('storage', 'failed_categories_sub_dir')


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


def get_ids_from_json(json_data: Dict[str, Any]) -> List[int]:
    """
    Extract product IDs from the given JSON data with thorough field existence checks.

    Args:
        json_data (Dict[str, Any]): The JSON data.

    Returns:
        List[int]: List of product IDs.
    """
    product_ids = []

    data = json_data.get("data")
    if data is None:
        logger.error("Missing 'data' field in JSON response.")
        return product_ids

    make_search = data.get("makeSearch")
    if make_search is None:
        logger.error("Missing 'makeSearch' field in 'data'.")
        return product_ids  #

    items = make_search.get("items")
    if items is None:
        logger.error("Missing 'items' field in 'makeSearch'.")
        return product_ids
    if not isinstance(items, list):
        logger.error(f"'items' field is not a list. Received type: {type(items)}")
        return product_ids

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning(f"Item at index {index} is not a dictionary. Skipping.")
            continue

        catalog_card = item.get("catalogCard")
        if catalog_card is None:
            logger.warning(f"Missing 'catalogCard' in item at index {index}. Skipping.")
            continue

        if not isinstance(catalog_card, dict):
            logger.warning(f"'catalogCard' in item at index {index} is not a dictionary. Skipping.")
            continue

        product_id = catalog_card.get("productId")
        if product_id is None:
            logger.warning(f"Missing 'productId' in 'catalogCard' at index {index}. Skipping.")
            continue

        if not isinstance(product_id, int):
            logger.warning(f"'productId' in 'catalogCard' at index {index} is not an integer. Skipping.")
            continue

        product_ids.append(product_id)

    if not product_ids:
        logger.info("No product IDs extracted from JSON data.")
    else:
        logger.debug(f"Extracted {len(product_ids)} product IDs.")

    return product_ids


def get_product_ids_by_category(token_manager: TokenManager,
                                category_id: int,
                                amount: int = 0,
                                page_limit: int = 100,
                                request_retries: int = 10,
                                backoff_factor: int = 1,
                                main_url: str = "https://uzum.uz/ru",
                                graphql_url: str = "https://graphql.uzum.uz/",
                                save_data: bool = False,
                                **kwargs) -> Tuple[List[int], int]:
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

    if not token_manager:
        logger.info("Initiating tokenManager in 'get_product_ids_by_category'.")
        token_manager = TokenManager(
            url=main_url,
            max_retries=kwargs.get('token_retries', 5),
            save_token=kwargs.get('save_token', False),
            save_cookies=False
        )
        auth_token = token_manager.get_token_instance()
        if auth_token is None:
            raise FileNotFoundError("Failed to get authorization token.")
    else:
        auth_token = token_manager.token

    ua = UserAgent()
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
        'x-iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7',
        'Connection': 'keep-alive'
    }

    host = graphql_url.split('//')[1].split('/')[0]
    endpoint = '/'

    payload_json = graphql_query_generator.generate_query()
    query_sort_types = ['BY_RELEVANCE_DESC', 'BY_RELEVANCE_ASC',
                        'BY_RATING_DESC', 'BY_RATING_ASC', 'BY_ORDERS_NUMBER_DESC', 'BY_ORDERS_NUMBER_ASC', 'BY_DATE_ADDED_ASC', 'BY_DATE_ADDED_DESC', 'BY_PRICE_ASC', 'BY_PRICE_DESC']
    query_sort_ind = 0
    OFFSET_LIMIT = 10000
    items_offset = 0
    data_list = []
    prev_data = []
    request_attempts = 0
    done = False
    status = None

    proxy_manager = ProxyManager.from_json_file("data/proxy/proxy.json")
    conn = None
    current_proxy_ip = None
    use_direct_connection = False
    proxy_timeout = 10
    proxy_manager_timeout = 10
    batch_size = 10000
    ind = 0
    proxy_ind = 0

    def wait_with_backoff(request_attempts: int, backoff_factor: float) -> None:
        logger.info(f"Server rejected. Attempt number {request_attempts}")
        wait_time = backoff_factor * (2 ** request_attempts)
        logger.info(f"Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    def make_connection(timeout: float = proxy_timeout if proxy_manager_timeout else 10,
                        pm_timeout: int = proxy_manager_timeout if proxy_manager_timeout else 10,
                        put_to_sleep: bool = False,
                        make_direct_connection: bool = use_direct_connection if use_direct_connection else False
                        ) -> Tuple[http.client.HTTPSConnection, str]:
        nonlocal conn
        nonlocal current_proxy_ip
        nonlocal proxy_ind

        def direct_connection() -> http.client.HTTPSConnection:
            if request_attempts > 0:
                wait_with_backoff(request_attempts, backoff_factor)
            return http.client.HTTPSConnection(host)

        if not make_direct_connection:
            if conn is not None:  # Close the previous connection before establishing a new one
                logger.debug(f"Closing connection for batch {ind // batch_size}")
                conn.close()
                if current_proxy_ip and put_to_sleep:
                    logger.debug(f"Setting to sleep proxy {current_proxy_ip}")
                    proxy_manager.sleep_proxy(current_proxy_ip, timeout)
                    proxy_ind = 0
            logger.debug(f"Establishing connection for batch {ind // batch_size + 1}")
            headers['User-Agent'] = ua.random
            try:
                logger.debug(f"Picking a proxy and establishing a connection")
                conn, current_proxy_ip = proxy_manager.make_connection(host, pm_timeout)
            except:
                logger.warning(f"No proxy connection! Establishing direct connection to {host}")
                conn = direct_connection()
                current_proxy_ip = None
        else:
            logger.debug(f"Establishing direct connection to {host}")
            conn = direct_connection()
            current_proxy_ip = None
        return conn, current_proxy_ip

    try:
        if proxy_ind % batch_size == 0:
            conn, current_proxy_ip = make_connection()

        while not done and request_attempts <= request_retries:
            graphql_query_generator.set_query_variables(
                data=payload_json, category_id=f'{category_id}', offset=items_offset, limit=page_limit, sort=query_sort_types[query_sort_ind])

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
                        raise ValueError(
                            "Empty response data from graphql query")

                    json_data = json.loads(decoded_data)

                    # Check for errors in the response
                    if 'errors' in json_data:
                        error_messages = [
                            error.get('message', 'Unknown error') for error in json_data['errors']]
                        error_429 = False
                        for error_message in error_messages:
                            logger.warning(f'GraphQL Error: {error_message}')
                            if '429' in error_message:
                                error_429 = True

                        if error_429:
                            logger.warning("429: Blocked by the server due to too many requests.")
                            status = 429
                            if request_attempts == 0:
                                auth_token = token_manager.get_token_instance()
                                headers['Authorization'] = f'Bearer {auth_token}'
                            request_attempts += 1
                            if request_attempts > 1:
                                retry_time = int(response.headers.get("Retry-After", 1))
                                proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                                conn, current_proxy_ip = make_connection(timeout=retry_time)
                            else:
                                conn, current_proxy_ip = make_connection()
                            # conn.close()
                            # wait_with_backoff(request_attempts, backoff_factor)
                            # if request_attempts == 0:
                            #     headers['User-Agent'] = ua.random
                            #     new_token = token_manager.get_token_instance()
                            #     if new_token is not None:
                            #         auth_token = new_token
                            #         headers['Authorization'] = f'Bearer {
                            #             auth_token}'
                            # request_attempts += 1

                            # conn = http.client.HTTPSConnection(host)
                            continue

                    data = get_ids_from_json(json_data)
                    if amount == 0:
                        amount = json_data.get("data", {}).get(
                            "makeSearch", {}).get("total")
                    if len(data) > 0:
                        data_list.extend(data)
                    else:
                        done = True
                        amount = json_data.get("data", {}).get(
                            "makeSearch", {}).get("total")

                    logger.debug(f'Collected {len(data)} of total {len(data_list)} collected items in category {category_id}')

                    items_offset += min(page_limit, amount - len(data_list))
                    if (len(data_list) >= amount) or (data == prev_data):
                        done = True

                    # If reached the offset limit, try other types of query sorting to extract maximum data
                    if items_offset >= OFFSET_LIMIT:
                        if query_sort_ind < len(query_sort_types) - 1:
                            items_offset = 0
                            query_sort_ind += 1
                            logger.info(f"Reached the API offset limit of 10,000. Switching to sort type {
                                        query_sort_types[query_sort_ind]}")
                            # add 10000 to prevent stopping (the amount is now irrelevant)
                            amount += OFFSET_LIMIT
                        else:
                            done = True

                    prev_data = data
                    request_attempts = 0
                    ind += 1
                    proxy_ind += 1

                elif response.status == 401:  # authorization failed
                    logger.warning(f"{response.status}: Authorization failed during the product API request; retrieving a new token...")
                    # wait_with_backoff(request_attempts, backoff_factor)
                    auth_token = token_manager.get_token_instance()
                    headers['Authorization'] = f'Bearer {auth_token}'
                    request_attempts += 1
                    if request_attempts > 1:
                        conn, current_proxy_ip = make_connection()
                    else:
                        conn, current_proxy_ip = make_connection(put_to_sleep=False)
                    # logger.info(f"{response.status}: Authorization failed during the GraphQL query; retrieving a new token...")
                    # conn.close()
                    # wait_with_backoff(request_attempts, backoff_factor)
                    # auth_token = token_manager.get_token_instance()
                    # logger.info(auth_token)
                    # headers['Authorization'] = f'Bearer {auth_token}'
                    # request_attempts += 1
                    # conn = http.client.HTTPSConnection(host)

                elif response.status == 429:  # too many requests
                    retry_time = int(response.headers.get("Retry-After", 1))
                    logger.warning("429: Blocked by the server due to too many requests.")
                    # wait_with_backoff(request_attempts, backoff_factor)
                    request_attempts += 1
                    if request_attempts > 1:
                        retry_time = int(response.headers.get("Retry-After", 1))
                        proxy_manager_timeout = max(retry_time, proxy_manager_timeout)
                        conn, current_proxy_ip = make_connection(timeout=retry_time)
                    else:
                        conn, current_proxy_ip = make_connection()
                    continue
                    # # Server blocking due to multiple requests
                    # logger.info("429: Blocked by a server due to too many requests.")
                    # headers['User-Agent'] = ua.random
                    # wait_with_backoff(request_attempts, backoff_factor)
                    # request_attempts += 1
                    # continue
                else:
                    raise ValueError(f"Bad response status on a GraphQL query: {
                        response.status}")
            except Exception as e:
                logger.error(
                    f'Failed to receive data from a GraphQl query: {e}')
                break
    except Exception as e:
        logger.error(f"In get_products_id_by_category: {e}")
    finally:
        proxy_manager.shutdown_scheduler()
        if conn is not None:
            conn.close()

    if len(data_list) != 0:
        logger.info(f"Finished retrieving category ids. Total collected {
                    len(data_list)} out of {amount} in GraphQL in category {category_id}")
        data_list = list(set(data_list))
        logger.info(f"Total unique ids: {len(data_list)} in category {category_id}, return status: {status}")
        if save_data:
            save_to_file(data_list, f'category_{category_id}_pr_ids', 'products_by_category', separate_folder=False)
    else:
        logger.warning(f"No items collected from category {category_id}, return status: {status}")

    return data_list, status


def fetch_product_ids_by_categories(categories: List[Dict[str, Any]],
                                    main_url: str = "https://uzum.uz/ru",
                                    graphql_url: str = "https://graphql.uzum.uz/",
                                    save_data: bool = True,
                                    load_most_recent_if_failed: bool = True,
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
    token_manager = TokenManager(
        url=main_url,
        max_retries=kwargs.get('token_retries', 5),
        save_token=kwargs.get('save_token', False),
        save_cookies=False
    )
    auth_token = token_manager.get_token_instance()

    try:
        if auth_token is not None:
            p_ids = []
            failed_categories = []
            for category in categories:
                category_ids, status = get_product_ids_by_category(token_manager, category_id=category['id'], amount=category['productAmount'], main_url=main_url, graphql_url=graphql_url, save_data=save_data)
                if len(category_ids) > 0:
                    p_ids.extend(category_ids)
                if status != 200:
                    failed_categories.append({"id": category['id'], "productAmount": category['productAmount'], "status": status})

            logger.info(f"Total {len(p_ids)} ids fetched.")
            p_ids = list(set(p_ids))
            logger.info(f"Total unique ids fetched: {len(p_ids)}")
            logger.info(f'Total number of failed categories: {
                        len(failed_categories)}')
            if sort_result:
                p_ids = sorted(p_ids)

            if save_data:
                if p_ids:
                    save_to_file(p_ids, product_ids_dir, product_ids_dir, separate_folder=False)

                if failed_categories:
                    save_to_file(failed_categories, 'failed_categories_ids', failed_categories_dir, separate_folder=False)

            if not p_ids and load_most_recent_if_failed:
                logger.warning(f"Could not fetch product IDs from {main_url}, loading most recent saved ids.")
                p_ids = load_last_saved_json(f'{data_dir}/{product_ids_dir}', 'product_ids')
            return p_ids
        else:
            raise FileNotFoundError("Failed to get authorization token.")
    except Exception as e:
        logger.error(f"In 'fetch_product_ids_by_category': {e}")


def main():
    parser = argparse.ArgumentParser(description='Fetch product IDs by category.')
    parser.add_argument('categories', metavar='CATEGORY_ID', type=int, nargs='+',
                        help='Category IDs to fetch product IDs from.')
    parser.add_argument('-s', '--save', action='store_true',
                        help='Save fetched product IDs to file.')
    parser.add_argument('-l', '--load', action='store_true',
                        help='Load most recent product IDs if fetching fails.')
    parser.add_argument('-o', '--sort', action='store_true',
                        help='Sort the resulting product IDs.')
    args = parser.parse_args()

    categories = [{'id': cid, 'productAmount': 0} for cid in args.categories]
    logger.info("Starting to fetch product IDs for the input categories...")
    try:
        fetch_product_ids_by_categories(
            categories=categories,
            save_data=args.save,
            load_most_recent_if_failed=args.load,
            sort_result=args.sort
        )
    except Exception as e:
        logger.error(f"In {__file__}->main: {e}")


if __name__ == "__main__":
    main()
