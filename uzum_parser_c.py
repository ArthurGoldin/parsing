import http.client
import time
import json
from datetime import datetime
import os
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
            with open(f"data/root_categories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", 'w', encoding='utf-8') as file:
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


def get_product_ids_by_category(category_id: int = 1, page_limit: int = 100, request_retries: int = 5, backoff_factor: int = 1) -> list:
    global auth_token
    global token_manager
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'ru-RU',
        'apollographql-client-name': 'web-customers',
        'apollographql-client-version': '1.25.2',
        'Authorization': f'Bearer {auth_token}',
        'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=dcdef1759da34ae6894f8629c5d59343',
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

    items_collected = 0
    items_offset = 0
    data_list = []
    request_attempts = 0
    done = False
    amount = None

    while not done and request_attempts < request_retries:
        graphql_query_generator.set_query_variables(
            payload_json, category_id, items_offset, page_limit)

        conn = http.client.HTTPSConnection(host)
        try:
            conn.request("POST", endpoint, json.dumps(
                payload_json), headers=headers)
            response = conn.getresponse()
            if response.status == 200:
                request_attempts = 0

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
                    for error_message in error_messages:
                        logger.error(f'GraphQL Error: {error_message}')
                    raise ValueError(f"GraphQL query failed with errors: {
                                     error_messages}")

                data = get_ids_from_json(json_data)
                if len(data) > 0:
                    data_list.extend(data)
                    if len(data_list) > 10000:
                        done = True
                        logger.info('Stopped collecting ids for debugging')
                else:
                    done = True
                    amount = json_data.get("data", {}).get(
                        "makeSearch", {}).get("total")
                    logger.info(f"Finished retrieving category ids. Total collected {
                                len(data_list)} out of {amount} by GraphQl amount")

                items_collected = len(data_list)
                items_offset += page_limit

                logger.info(f'Collected {len(data)} of total {
                            items_collected} collected items in category {category_id}.')

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
                logger.info(f"Attempt number {request_attempts}")
                wait_time = backoff_factor * (2 ** request_attempts)
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
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
        logger.info(f"Collected {len(data_list)
                                 } ids of category {category_id}")

        with open(f'{data_dir}/product_ids_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv', 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(data_list)
    else:
        logger.info(f"No items collected from category {category_id}")

    return data_list


def load_category_tree(file_path: str):
    """Load category tree from a JSON file."""
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def find_leaf_categories(category_tree):
    """Recursively find all leaf categories in the category tree."""
    leaf_categories = []

    def traverse(node):
        if not node['children']:
            leaf_categories.append(node)
        else:
            for child in node['children']:
                traverse(child)

    traverse(category_tree)
    return leaf_categories


def combine_products_into_tree(category_tree, products_by_category):
    """Combine fetched products into the category tree."""
    def traverse(node):
        node['products'] = products_by_category.get(node['id'], [])
        for child in node['children']:
            traverse(child)

    traverse(category_tree)
    return category_tree


def fetch_data(root_categories_flag=False):
    if root_categories_flag:
        root_categories = get_root_categories()

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
        category_ids = get_product_ids_by_category(
            category_id=1)


if __name__ == "__main__":

    try:
        fetch_data()
    except Exception as e:
        logger.error(f'Data fetching failed: {e}')
