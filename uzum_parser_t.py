import subprocess
import time
import json
from datetime import datetime
import os
import csv
import pandas as pd
import logging

from get_token import get_token_instance
import graphql_query_generator

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


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


def get_token_with_retry(url, max_tries=5):
    attempt = 0
    while attempt < max_tries:
        auth_token = get_token_instance(url)
        if auth_token is not None:
            return auth_token
        else:
            logger.info("No authorization token received. Retrying...")
        attempt += 1
        time.sleep(2)
    return None


def get_data_from_json(file: dict) -> list:
    data_list = []
    for item in file["data"]["makeSearch"]["items"]:
        prId = item.get("catalogCard").get("productId")
        title = item.get("catalogCard").get("title")
        feedbackQuantity = item.get("catalogCard").get("feedbackQuantity")
        minFullPrice = item.get("catalogCard").get("minFullPrice")
        minSellPrice = item.get("catalogCard").get("minSellPrice")
        ordersQuantity = item.get("catalogCard").get("ordersQuantity")
        rating = item.get("catalogCard").get("rating")
        data_list.append({
            'id': prId,
            'name': title,
            'price': minFullPrice,
            'salePrice': minSellPrice,
            'rating': rating,
            'feedbacks': feedbackQuantity,
            'orders': ordersQuantity,
            'link': f'{main_url}/product/{prId}'
        })
    return data_list


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


def gen_curl_command(auth_token, payload_json, graphql_url="https://graphql.uzum.uz/", main_url="https://uzum.uz/ru/"):
    return [
        'curl', graphql_url,
        '-H', 'accept: */*',
        '-H', 'accept-language: ru-RU',
        '-H', 'apollographql-client-name: web-customers',
        '-H', 'apollographql-client-version: 1.25.2',
        '-H', f"Authorization: Bearer {auth_token}",
        '-H', 'baggage: sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=dcdef1759da34ae6894f8629c5d59343',
        '-H', 'content-type: application/json',
        '-H', 'origin: https://uzum.uz',
        '-H', 'priority: u=1, i',
        '-H', f"referer: {main_url}",
        '-H', 'sec-ch-ua: "Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        '-H', 'sec-ch-ua-mobile: ?0',
        '-H', 'sec-ch-ua-platform: "macOS"',
        '-H', 'sec-fetch-dest: empty',
        '-H', 'sec-fetch-mode: cors',
        '-H', 'sec-fetch-site: same-site',
        '-H', 'sentry-trace: dcdef1759da34ae6894f8629c5d59343-a55aaf4639abcfa1',
        '-H', 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        '-H', 'x-context: null',
        '-H', 'x-iid: d7e47b3b-1ea6-4b34-9362-d9169f1250e7',
        '--data', json.dumps(payload_json)
    ]


def fetch_data_with_curl(category_id, auth_token, graphql_url):
    """Fetch data using curl command."""
    payload_json = graphql_query_generator.generate_query()

    graphql_query_generator.set_query_variables(
        payload_json, category_id, 0, 1)

    try:
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


def save_excel(data: list, filename: str):
    try:
        df = pd.DataFrame(data)
        writer = pd.ExcelWriter(f'{filename}.xlsx')
        df.to_excel(writer, sheet_name='data', index=False)

        writer.sheets['data'].set_column(0, 1, width=10)  # id
        writer.sheets['data'].set_column(1, 2, width=90)  # name
        writer.sheets['data'].set_column(2, 3, width=8)  # price
        writer.sheets['data'].set_column(3, 4, width=8)  # sale price
        writer.sheets['data'].set_column(4, 5, width=6)  # rating
        writer.sheets['data'].set_column(5, 6, width=10)  # num of feedbacks
        writer.sheets['data'].set_column(6, 7, width=8)  # num of orders
        writer.sheets['data'].set_column(7, 8, width=34)  # link
        writer.close()
        logger.info(f'Data saved to {filename}.xlsx\n')
    except Exception as e:
        logger.error(f"Error in saving to .xlsx file: {e}")


def fetch_products_for_category(category_id: int, auth_token: str, main_url: str = "https://uzum.uz/ru/", graphql_url: str = "https://graphql.uzum.uz/", data_dir: str = "data"):
    # Run first query to get variables values and check connection
    data_list = []

    data = fetch_data_with_curl(category_id, auth_token, graphql_url)
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


if __name__ == "__main__":
    main_url = "https://uzum.uz/ru"
    graphql_url = "https://graphql.uzum.uz/"
    category_id = "12690"
    data_dir = "data"
    auth_token = None
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    try:
        # auth_token = get_token_with_retry(url=main_url)
        auth_token = get_token_instance(main_url, 4)
        if auth_token is None:
            logger.error(
                "Can't retrieve authorization token! Shutting down...")
            exit()

    except Exception as e:
        logger.error(
            f"In uzum_parser.main: something went wrong during retrieving authorization token: {e}")

    try:
        fetch_products_for_category(category_id, auth_token,
                                    main_url, graphql_url, data_dir)

    except Exception as e:
        logger.error(f"Error in uzum_parser.get_data_by_category: {e}")
    finally:
        logger.info("Finished.")
