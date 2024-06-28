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
            with open(f"data/root_categories_{datetime.now().strftime("%Y%m%d_%H%M%S")}", 'w', encoding='utf-8') as file:
                json.dump(root_categories, file, ensure_ascii=False, indent=4)
            logger.info(f'Collected root-categories from {main_url}')
        else:
            raise ValueError(f"HTTP error occurred while fetching root-categories: Status code {
                response.status}")
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


def get_product_ids_by_category(category_id: int, amount: int) -> list:
    global auth_token
    global token_manager
    auth_token = "eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE5NTAwMzE3LCJzdWIiOiI1ZjBlMGY4Ny00YTMyLTQ3ZTEtYTMwOC1jZWNlN2M3Y2Y5ZGUiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTk1MDEwMzd9.Rb_hV1-eboflR5zxV3y_NbLQJ3HUIH9wc5BeJf_DLsjhG-hVT4Y6K4y5SAD9tp7hN_9hqzeUHCB33-XYfdKWBQ"
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
    host = graphql_url.split('//')[1]
    endpoint = '/'

    host = 'graphql.uzum.uz'
    endpoint = '/'

    payload_json = graphql_query_generator.generate_query()

    items_collected = 0
    items_offset = 0
    data_list = []
    amount = 1
    while items_collected < amount:
        graphql_query_generator.set_query_variables(
            payload_json, category_id, items_offset, 3)

        conn = http.client.HTTPSConnection(host)
        try:
            conn.request("POST", endpoint, json.dumps(
                payload_json), headers=headers)
            response = conn.getresponse()
            if response.status == 200:
                logger.info(f'Response status {response.status}')
                response_data = response.read()
                content_encoding = response.getheader('Content-Encoding')

                if content_encoding:
                    response_data = decompress_http_response(
                        response_data, content_encoding)
                decoded_data = response_data.decode('utf-8')

                if not decoded_data:
                    raise ValueError("Empty response data from graphql query")

                json_data = json.loads(decoded_data)
                data_list.extend(get_ids_from_json(json_data))

                with open(f"data/category_ids_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w", encoding='utf-8') as json_file:
                    json.dump(json_data, json_file,
                              ensure_ascii=False, indent=4)

                items_collected = len(data_list)
                items_offset += min(100, amount - items_collected)

                logger.info(f'Collected {items_collected} of total {
                            amount} items in category {category_id}.')

            elif response.status == 401:  # authorization failed
                logger.info(
                    f"{response.status}: Authorization failed during the GraphQL query; retrieving a new token...")
                auth_token = token_manager.get_token_instance()
                headers['Authorization'] = f'Bearer {auth_token}'
            elif response.status == 429:
                # Server blocking due to multiple requests
                pass
            else:
                raise ValueError(f"Bad response status on a GraphQL query: {
                                 response.status}")

        except Exception as e:
            logger.error(f'Failed to receive data from a GraphQl query: {e}')
        finally:
            conn.close()

    if len(data_list) != 0:
        logger.info(f"Collected {len(data_list)
                                 } ids of category {category_id}")
    else:
        logger.info(f"No items collected from category {category_id}")

    return data_list


def get_product_ids_by_category1(category_id: int, amount: int) -> list:
    global auth_token
    auth_token = "eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE5NTAwMzE3LCJzdWIiOiI1ZjBlMGY4Ny00YTMyLTQ3ZTEtYTMwOC1jZWNlN2M3Y2Y5ZGUiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTk1MDEwMzd9.Rb_hV1-eboflR5zxV3y_NbLQJ3HUIH9wc5BeJf_DLsjhG-hVT4Y6K4y5SAD9tp7hN_9hqzeUHCB33-XYfdKWBQ"
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
    host = graphql_url.split('//')[1]
    endpoint = '/'

    host = 'graphql.uzum.uz'
    endpoint = '/'

    payload_json = graphql_query_generator.generate_query()

    amount = 1
    items_collected = 0
    items_offset = 0
    data_list = []

    try:
        while items_collected < amount:

            graphql_query_generator.set_query_variables(
                payload_json, category_id, items_offset, 3)

            conn = http.client.HTTPSConnection(host)
            conn.request("POST", endpoint, json.dumps(
                payload_json), headers=headers)
            response = conn.getresponse()
            if response.status == 200:
                logger.info(f'Response status {response.status}')
                response_data = response.read()
                content_encoding = response.getheader('Content-Encoding')

                if content_encoding:
                    response_data = decompress_http_response(
                        response_data, content_encoding)
                decoded_data = response_data.decode('utf-8')

                if not decoded_data:
                    raise ValueError("Empty response data from graphql query")

                # Remove this later
                json_data = json.loads(decoded_data)

                # Maybe allocate a list of size 'amount' for better performance
                data_list.extend(get_ids_from_json(json_data))

                with open(f"data/category_ids_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json", "w", encoding='utf-') as json_file:
                    json.dump(json_data, json_file,
                              ensure_ascii=False, indent=4)

                items_collected = len(data_list)
                items_offset += min(100, amount - items_collected)

                logger.info(f'Collected {items_collected} of total {
                    amount} items in category {category_id}.')

            elif response.status == 401:  # authorization failed
                logger.info(
                    f"{response.status}: Authorization failed during the GraphQL query; retrieving a new token...")
                global token_manager
                auth_token = token_manager.get_token_instance()
                headers['Authorization'] = f'Bearer {auth_token}'
            else:
                raise ValueError(f"Bad response status on a GraphQL query: {
                                 response.status}")
            conn.close()

    except Exception as e:
        logger.error(f'Failed to receive data from a GraphQl query: {e}')
    finally:
        if conn.sock:
            conn.close()

    if len(data_list) != 0:
        logger.info(f"Collected {len(data_list)
                                 } ids of category {category_id}")
    else:
        logger.info(f"No items collected from category {
                    category_id}")

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
            category_id=15335, amount=121)


if __name__ == "__main__":

    try:
        fetch_data()
    except Exception as e:
        logger.error(f'Data fetching failed: {e}')
    # category_id = "12690"
    # if not os.path.exists(data_dir):
    #     os.makedirs(data_dir)

    # try:
    #     fetch_products_for_category(category_id, auth_token)

    # except Exception as e:
    #     logger.error(f"Error in uzum_parser.get_data_by_category: {e}")
    # finally:
    #     logger.info("Finished.")
