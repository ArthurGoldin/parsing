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
    items = json_data.get("data", []).get("makeSearch", []).get("items", [])
    data_list = [item.get("catalogCard").get("productId")
                 for item in items if "productId" in item]
    return data_list


def get_product_ids_by_category(category_id: int, amount: int) -> list:
    global auth_token

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

    conn = http.client.HTTPSConnection(host)
    try:
        while items_collected < amount:
            graphql_query_generator.set_query_variables(
                payload_json, category_id, items_offset, 1)

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
                    'Authorization failed during the GraphQL query; retrieving a new token...')
                global token_manager
                auth_token = token_manager.get_token_instance()
                headers['Authorization'] = f'Bearer {auth_token}'
            else:
                print(response.status)
                raise ValueError(f"Bad response status on a GraphQL query: {
                                 response.status}")

    except Exception as e:
        logger.error(e)

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


def check_response_with_retry(response: dict) -> bool:
    if response is not None:
        if 'errors' in response:
            unauthorized = any(
                error.get('extensions', {}).get(
                    'code') == 'UNAUTHORIZED' or error.get('message') == 'Unauthorized'
                for error in response['errors']
            )
            if unauthorized:
                logger.error(
                    "Error: Authorization token is declined. Getting a new token...")
                auth_token = get_token_with_retry(service=None, url=main_url)
                if auth_token is None:
                    logger.error(
                        "Can't retrieve authorization token! Shutting down...")
                    return False
            else:
                logger.error("Errors in response: %s", response['errors'])
                return False
        else:
            return True
    else:
        logger.error("No response received or an error occurred.")
        return False


def generate_headers(auth_token, type=0, main_url="https://uzum.uz"):

    if type == 0:
        return {
            'accept': 'application/json',
            'accept-language': 'ru-RU',
            'authorization': f'Bearer {auth_token}',
            'baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=09833b5c87c54335ba74a0a562605c73,sentry-sample_rate=0.001,sentry-transaction=main,sentry-sampled=false',
            'content-type': 'application/json',
            'origin': f'{main_url}',
            'priority': 'u=1, i',
            'referer': f'{main_url}',
            'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'sentry-trace': '09833b5c87c54335ba74a0a562605c73-b47ba3aad8d7c64e-0',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'x-iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7'
        }
    if type == 1:
        return {
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


def fetch_root_categories(auth_token):
    headers = generate_headers(auth_token, 0)


def fetch_data_with_request(category_id, auth_token, graphql_url):
    """Fetch data using request command."""
    host = graphql_url
    endpoint = '/'
    headers = generate_headers(auth_token)
    payload_json = graphql_query_generator.generate_query()
    graphql_query_generator.set_query_variables(
        payload_json, category_id, 0, 1)

    try:
        conn = http.client.HTTPConnection(host)
        conn.request

        curl_command = gen_curl_command(auth_token, payload_json, graphql_url)

        result = subprocess.run(curl_command, capture_output=True, text=True)
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if check_response_with_retry(response):
                return get_data_from_json(response)
        else:
            logger.error(f"Failed to fetch data for category {
                category_id}: {result.stderr}")
    except Exception as e:
        logger.error(f"Error in fetch_data_with_curl(): {e}")
    return []


def fetch_products_for_category(category_id: int, auth_token: str, main_url: str = "https://uzum.uz/ru/", graphql_url: str = "https://graphql.uzum.uz/", data_dir: str = "data"):
    # Run first query to get variables values and check connection
    data_list = []

    data = fetch_data_with_request(category_id, auth_token, graphql_url)
    if data:
        data_list.extend(data)

    # if check_response_with_retry(response):
    #     is_done = False
    #     category_name = response["data"]["makeSearch"]["category"]["title"]
    #     total_items = response["data"]["makeSearch"]["total"]
    #     items_collected = 0
    #     items_offset = 0
    #     logger.info("First response received.")
    # else:
    #     is_done = True

    # while not is_done:
    #     set_query_variables(payload_json, category_id,
    #                         items_offset, 1, sort="BY_ORDERS_NUMBER_DESC")

    #     if check_response_with_retry(response):
    #         data_list.extend(get_data_from_json(response))
    #         items_collected = len(data_list)
    #         items_offset += min(100, total_items - items_collected)
    #         logger.info(f'Collected {items_collected} of total {
    #                     total_items} items in {category_name}.')
    #     else:
    #         break

    #     if items_collected >= total_items:
    #         logger.info('Finished collecting.')
    #         is_done = True

    category_name = 'category'
    if len(data_list) != 0:
        print(f'data_list type: {type(data_list)}')
        print(f"{data_list}")
        # current_time = datetime.now().strftime("%Y%m%d_%H%M%S")

        # csv_file_name = os.path.join(
        #     data_dir, f'{category_name}_{current_time}.csv')
        # excel_file_name = os.path.join(
        #     data_dir, f'{category_name}_{current_time}')

        # # Save data_list to CSV with BOM
        # keys = data_list[0].keys() if data_list else []
        # with open(csv_file_name, 'w', newline='', encoding='utf-8-sig') as csv_file:
        #     dict_writer = csv.DictWriter(csv_file, fieldnames=keys)
        #     dict_writer.writeheader()
        #     dict_writer.writerows(data_list)
        # logger.info(f"Data saved to {csv_file_name}")

        # save_excel(data_list, excel_file_name)

    else:
        logger.info(f"No items collected from category {
                    category_name}")


def fetch_data():
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

    fetch_data()
    # category_id = "12690"
    # if not os.path.exists(data_dir):
    #     os.makedirs(data_dir)

    # try:
    #     fetch_products_for_category(category_id, auth_token)

    # except Exception as e:
    #     logger.error(f"Error in uzum_parser.get_data_by_category: {e}")
    # finally:
    #     logger.info("Finished.")
