import http.client
import time
import json
import logging
import logging.config
import zlib
import brotli
from typing import List, Tuple, Dict, Any
from fake_useragent import UserAgent
import sys
import configparser
from token_manager import TokenManager
import graphql_query_generator
from save_and_load_data import save_to_file, load_last_saved_csv

logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()

config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
product_ids_dir = config.get('storage', 'product_ids_sub_dir')
failed_categories_dir = config.get('storage', 'failed_categories_sub_dir')

token_manager = None
auth_token = None


# def save_csv(file: List[Any], file_name: str, sub_dir: str = "", add_date_time: bool = True) -> None:
#     """
#     Save the given data to a CSV file.

#     Args:
#         file (List[Any]): Data to be saved.
#         file_name (str): Name of the file.
#         sub_dir (str, optional): Sub-directory within the data directory.
#         add_date_time (bool, optional): Whether to append the current datetime to the file name.
#     """
#     dir_path = f"{data_dir}/{sub_dir}"
#     if not os.path.exists(dir_path):
#         os.makedirs(dir_path)

#     orig_file_name = file_name
#     if add_date_time:
#         file_name = f'{file_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

#     with open(f'{dir_path}/{file_name}.csv', 'w', newline='') as write_file:
#         writer = csv.writer(write_file)
#         writer.writerow(file)
#         logger.info(f"{orig_file_name} saved to a .csv file in {
#                     data_dir}/{sub_dir}")


# def load_last_saved_csv(directory: str, name: str) -> List[int]:
#     """
#     Load the last saved CSV file from the specified directory.

#     Args:
#         directory (str): The directory containing the CSV files.
#         name (str): The base name of the CSV files.

#     Returns:
#         List[int]: List of integers read from the CSV file.
#     """
#     try:
#         list_of_files = glob.glob(os.path.join(directory, f'{name}_*.csv'))
#         if not list_of_files:
#             raise FileNotFoundError(
#                 "No csv files found in the directory/category.")

#         latest_file = max(list_of_files, key=os.path.getctime)

#         with open(latest_file, newline='') as csvfile:
#             reader = csv.reader(csvfile)
#             for row in reader:
#                 int_list = [int(item) for item in row]
#         logger.info(f"Loaded most recent {
#                     name}. Total items: {len(int_list)}")
#         return int_list
#     except Exception as e:
#         logging.error(f'Failed to load the last saved csv file: {e}')
#         return []


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


def get_product_ids_by_category(category_id: int, amount: int = 0, page_limit: int = 100, request_retries: int = 10, backoff_factor: int = 1, main_url: str = "https://uzum.uz/ru", graphql_url: str = "https://graphql.uzum.uz/", save_category_ids: bool = False, **kwargs) -> Tuple[List[int], int]:
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
        'User-Agent': ua.random if ua else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
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

    try:
        conn = http.client.HTTPSConnection(host)

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
                            logger.error(f'GraphQL Error: {error_message}')
                            if '429' in error_message:
                                error_429 = True

                        if error_429:
                            status = 429
                            conn.close()
                            wait_with_backoff(request_attempts, backoff_factor)
                            if request_attempts == 0:
                                headers['User-Agent'] = ua.random
                                new_token = token_manager.get_token_instance()
                                if new_token is not None:
                                    auth_token = new_token
                                    headers['Authorization'] = f'Bearer {
                                        auth_token}'
                            request_attempts += 1
                            conn = http.client.HTTPSConnection(host)
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
                    headers['User-Agent'] = ua.random
                    wait_with_backoff(request_attempts, backoff_factor)
                    request_attempts += 1
                    continue
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
        conn.close()

    if len(data_list) != 0:
        logger.info(f"Finished retrieving category ids. Total collected {
                    len(data_list)} out of {amount} in GraphQL in category {category_id}")
        data_list = list(set(data_list))
        logger.info(f"Total unique ids: {len(data_list)} in category {
                    category_id}, return status: {status}")
        if save_category_ids:
            save_to_file(data_list, f'category_{category_id}_pr_ids', 'products_by_category', separate_folder=False)
    else:
        logger.warning(f"No items collected from category {category_id}, return status: {status}")

    return data_list, status


def fetch_product_ids_by_categories(categories: List[Dict[str, Any]], main_url: str = "https://uzum.uz/ru", graphql_url: str = "https://graphql.uzum.uz/", save_fetched_data: bool = True, load_most_recent_if_failed: bool = True, **kwargs) -> List[int]:
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
        max_retries=kwargs.get('token_retries', 5),
        save_token=kwargs.get('save_token', False),
        save_cookies=False
    )
    global auth_token
    auth_token = token_manager.get_token_instance()

    if auth_token is not None:
        p_ids = []
        failed_categories = []
        for category in categories:
            category_ids, status = get_product_ids_by_category(category_id=category['id'], amount=category['productAmount'], main_url=main_url, graphql_url=graphql_url)
            if len(category_ids) > 0:
                p_ids.extend(category_ids)
            if status != 200:
                failed_categories.append({"id": category['id'], "productAmount": category['productAmount'], "status": status})

        logger.info(f"Total {len(p_ids)} ids fetched.")
        p_ids = list(set(p_ids))
        logger.info(f"Total unique ids fetched: {len(p_ids)}")
        logger.info(f'Total number of failed categories: {
                    len(failed_categories)}')

        if save_fetched_data:
            if p_ids:
                save_to_file(p_ids, product_ids_dir, product_ids_dir, separate_folder=False)

            if failed_categories:
                save_to_file(failed_categories, 'failed_categories_ids', failed_categories_dir, separate_folder=False)
                # with open(f"{data_dir}/failed_categories/failed_categories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", 'w', encoding='utf-8') as file:
                #     json.dump(failed_categories, file,
                #               ensure_ascii=False, indent=4)

        if not p_ids and load_most_recent_if_failed:
            logger.warning(f"Could not fetch product IDs from {main_url}, loading most recent saved ids.")
            p_ids = load_last_saved_csv(f'{data_dir}/{product_ids_dir}', 'product_ids')
        return p_ids
    else:
        raise FileNotFoundError("Failed to get authorization token.")


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
        categories = []
        for category in arguments:
            categories.append({'id': int(category), 'productAmount': 0})
        logger.info("Starting to fetch product IDs for the input categories...")
        try:
            fetch_product_ids_by_categories(categories)
        except Exception as e:
            logger.error(f"In {sys.argv[0]}->main: {e}")
    else:
        logger.error("Wrong input arguments.")
