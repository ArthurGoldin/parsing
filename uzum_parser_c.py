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


def save_csv(file: list, file_name: str, sub_dir: str = "", add_date_time: bool = True):
    dir_path = f'{data_dir}/{sub_dir}'
    if not os.path.exists(data_dir):
        os.makedirs(dir_path)

    if add_date_time:
        file_name = f'{file_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    with open(f'{dir_path}/{file_name}.csv', 'w', newline='')as file:
        writer = csv.writer(file)
        writer.writerow(file)
        logger.info(f"{file_name.split('_')[0]} saved to a .csv file")


def decompress_http_response(response_data, encoding):
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


def get_root_categories():
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
                json.dump(root_categories, file, ensure_ascii=False, indent=4)
            logger.info(f'Collected root-categories from {main_url}')
        else:
            raise ValueError(
                f"HTTP error occurred while fetching root-categories: Status code {response.status}")
    except Exception as e:
        logger.error(e)
    finally:
        conn.close()

    return root_categories


def get_ids_from_json(json_data: dict) -> list:
    items = json_data.get("data", {}).get("makeSearch", {}).get("items", [])

    # Collect all productId values from the items
    product_ids = [item.get("catalogCard", {}).get(
        "productId") for item in items if "catalogCard" in item and "productId" in item["catalogCard"]]
    return product_ids


def get_product_ids_by_category(category_id: int, amount: int, page_limit: int = 100, request_retries: int = 8, backoff_factor: int = 1, save_category_ids: bool = False) -> list:
    global auth_token
    global token_manager
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'ru-RU',
        'apollographql-client-name': 'web-customers',
        'apollographql-client-version': '1.26.3',
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
        'x-iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7'
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

    def wait_with_backoff(request_attempts: int, backoff_factor: float):
        logger.info(f"Server rejected. Attempt number {request_attempts}")
        wait_time = backoff_factor * (2 ** request_attempts)
        logger.info(f"Retrying in {wait_time} seconds...")
        time.sleep(wait_time)

    while not done and request_attempts <= request_retries:
        if request_attempts > 0:
            wait_with_backoff(request_attempts, backoff_factor)
        graphql_query_generator.set_query_variables(
            data=payload_json, category_id=category_id, offset=items_offset, limit=page_limit, sort=query_sort_types[query_sort_ind])

        conn = http.client.HTTPSConnection(host)
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
                        if request_attempts == 0:
                            new_token = token_manager.get_token_instance()
                            if new_token is not None:
                                auth_token = new_token
                                headers['Authorization'] = f'Bearer {
                                    auth_token}'
                        request_attempts += 1
                        continue
                    # raise ValueError(f"GraphQL query failed with errors: {
                    #                  error_messages}")

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
                auth_token = token_manager.get_token_instance()

                headers['Authorization'] = f'Bearer {auth_token}'
                request_attempts += 1
            elif response.status == 429:
                # Server blocking due to multiple requests
                logger.info(
                    "429: Blocked by a server due to too many requests.")
                request_attempts += 1
                continue
            else:
                raise ValueError(f"Bad response status on a GraphQL query: {
                                 response.status}")
        except Exception as e:
            logger.error(f'Failed to receive data from a GraphQl query: {e}')
            break
        finally:
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


def load_last_saved_root_categories(directory: str) -> dict:
    try:
        # Get list of all root_categories JSON files in the directory
        list_of_files = glob.glob(os.path.join(
            directory, 'root_categories_*.json'))
        if not list_of_files:
            raise FileNotFoundError(
                "No root-categories files found in the directory.")

        # Find the most recent file
        latest_file = max(list_of_files, key=os.path.getctime)

        # Load the JSON data from the file
        with open(latest_file, 'r', encoding='utf-8') as file:
            root_categories = json.load(file)

        logging.info(f'Loaded root-categories from {latest_file}')
        return root_categories

    except Exception as e:
        logging.error(f'Failed to load the last saved root-categories: {e}')
        return None


def load_category_tree(file_path: str):
    """Load category tree from a JSON file."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def find_leaf_categories(category_tree):
    """Recursively find all leaf categories in the category tree."""
    leaf_categories = []

    def traverse(node):
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


def combine_products_into_tree(category_tree, products_by_category):
    """Combine fetched products into the category tree."""
    def traverse(node):
        node['products'] = products_by_category.get(node['id'], [])
        for child in node['children']:
            traverse(child)

    traverse(category_tree)
    return category_tree


def fetch_data():
    start_time = time.time()
    try:
        root_categories = get_root_categories()
        if root_categories is None:
            logger.warning(f"Failed to fetch root-categories from {
                main_url}, loading the most recent saved root-categories.")
            root_categories = load_last_saved_root_categories(
                f"{data_dir}/root_categories")
            if root_categories is not None:
                logger.info("Successfully loaded the root-categories.")
            else:
                raise FileNotFoundError("Failed to load root-categories.")

        leaf_categories = find_leaf_categories(root_categories)
        if leaf_categories:
            logger.info(f"Extracted {len(leaf_categories)
                                     } categories from root-categories.")
            save_csv(leaf_categories, 'leaf_categories', 'category_ids')
        else:
            raise AttributeError("Leaf categories not found")

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
            for category in leaf_categories:
                category_ids, status = get_product_ids_by_category(
                    category_id=category['id'], amount=category['productAmount'])
                if len(category_ids) > 0:
                    product_ids.extend(category_ids)
                if status != 200:
                    failed_categories.append(
                        {"id": category['id'], "productAmount": category['productAmount'], "status": status})

            logger.info(f"Total {len(product_ids)} ids fetched.")

            product_ids = list(set(product_ids))
            logger.info(f"Total unique ids fetched: {len(product_ids)}")
            if product_ids:
                save_csv(product_ids, 'product_ids', 'product_ids')

            if failed_categories:
                logger.info(f'Total number of failed categories: {
                            len(failed_categories)}')
                save_csv(failed_categories,
                         'failed_categories_ids', 'failed_categories')
        else:
            raise FileNotFoundError("Failed to get authorization token.")

    except Exception as e:
        logger.error(f"Could not fetch data: {e} Exiting...")
    finally:
        end_time = time.time()
        logger.info(f"Total execution time: {
                    (end_time - start_time):.2f} seconds")


if __name__ == "__main__":

    try:
        fetch_data()
    except Exception as e:
        logger.error(f'Data fetching failed: {e}')
