import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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


def generate_fetch_js_code(payload_json, auth_token, graphql_url="https://graphql.uzum.uz/"):
    js_code = f"""
    const payload = {json.dumps(payload_json)};
    fetch("{graphql_url}", {{
        method: 'POST',
        headers: {{
            "accept": "*/*",
            "accept-language": "ru-RU",
            "apollographql-client-name": "web-customers",
            "apollographql-client-version": "1.24.0",
            "authorization": "Bearer {auth_token}",
            "baggage": "sentry-environment=production,sentry-release=uzum-market@1.24.0,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=9d83c94f728e461abfa24082e9b19b80",
            "content-type": "application/json",
            "origin": "https://uzum.uz/ru/",
            "priority": "u=1, i",
            "referer": "https://uzum.uz/ru/",
            "sec-ch-ua": "\\"Google Chrome\\";v=\\"125\\", \\"Chromium\\";v=\\"125\\", \\"Not.A/Brand\\";v=\\"24\\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Windows",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "sentry-trace": "9d83c94f728e461abfa24082e9b19b80-99f27a90be006cd9-0",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "x-context": "null",
            "x-iid": "8d8f8d7a-2d63-4668-8655-3e56f88c710c"
        }},
        body: JSON.stringify(payload)
    }})
    .then(response => response.json())
    .then(data => {{
        console.log('GraphQL response:', data);
        window.graphqlResponse = data;  // Store response in a global variable
    }})
    .catch(error => {{
        console.error('Error:', error);
        window.graphqlResponse = null;
    }});
    """
    return js_code


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


def fetch_products_for_category(driver: uc.Chrome, category_id: int, auth_token: str, main_url: str = "https://uzum.uz/ru/", graphql_url: str = "https://graphql.uzum.uz/", data_dir: str = "data"):

    payload_json = graphql_query_generator.generate_query()

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # Run first query to get variables values and check connection
    graphql_query_generator.set_query_variables(payload_json, category_id, 0,
                                                0, sort="BY_ORDERS_NUMBER_DESC")
    js_code = generate_fetch_js_code(
        payload_json, auth_token, graphql_url)

    driver.get(main_url)
    WebDriverWait(driver, 20).until(EC.title_contains("Uzum Market"))

    logger.info(f"PAGE LOADED: {driver.title}")
    driver.execute_script(js_code)

    WebDriverWait(driver, 20).until(lambda d: d.execute_script(
        "return window.graphqlResponse") is not None)
    response = driver.execute_script("return window.graphqlResponse;")

    if check_response_with_retry(response):
        is_done = False
        category_name = response["data"]["makeSearch"]["category"]["title"]
        total_items = 1  # response["data"]["makeSearch"]["total"]
        items_collected = 0
        items_offset = 0
        logger.info("First response received.")
    else:
        is_done = True

    data_list = []

    while not is_done:
        graphql_query_generator.set_query_variables(payload_json, category_id,
                                                    items_offset, 1, sort="BY_ORDERS_NUMBER_DESC")
        js_code = generate_fetch_js_code(
            payload_json, auth_token, graphql_url)

        driver.get(main_url)
        driver.execute_script(js_code)

        WebDriverWait(driver, 20).until(lambda d: d.execute_script(
            "return window.graphqlResponse") is not None)
        response = driver.execute_script(
            "return window.graphqlResponse;")

        if check_response_with_retry(response):
            data_list.extend(get_data_from_json(response))
            items_collected = len(data_list)
            items_offset += min(100, total_items - items_collected)
            logger.info(f'Collected {items_collected} of total {
                        total_items} items in {category_name}.')
            # with open('json.json', 'w', encoding='utf-8') as json_file:
            #     json.dump(response, json_file, ensure_ascii=False, indent=4)
        else:
            break

        if items_collected >= total_items:
            logger.info('Finished collecting.')
            is_done = True

    if len(data_list) != 0:
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_file_name = os.path.join(
            data_dir, f'{category_name}_{current_time}.csv')
        excel_file_name = os.path.join(
            data_dir, f'{category_name}_{current_time}')

        # Save data_list to CSV with BOM
        keys = data_list[0].keys() if data_list else []
        with open(csv_file_name, 'w', newline='', encoding='utf-8-sig') as csv_file:
            dict_writer = csv.DictWriter(csv_file, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(data_list)
        logger.info(f"Data saved to {csv_file_name}")

        save_excel(data_list, excel_file_name)

    else:
        logger.info(f"No items collected from category {
                    category_name}")


if __name__ == "__main__":
    main_url = "https://uzum.uz/ru"
    graphql_url = "https://graphql.uzum.uz/"
    category_id = "12690"
    data_dir = "data"
    auth_token = None
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

    options = uc.ChromeOptions()

    try:
        driver = uc.Chrome(options=options)
        fetch_products_for_category(driver, category_id, auth_token,
                                    main_url, graphql_url, data_dir)

    except Exception as e:
        logger.error(f"Error in uzum_parser: {e}")
    finally:
        try:
            for handle in driver.window_handles[:-1]:
                driver.switch_to.window(handle)
                logger.info("Closing %s" % driver.current_url)
                driver.close()
            driver.quit()
        except Exception as e:
            logger.error(f"Error during driver quit: {e}")
