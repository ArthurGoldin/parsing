import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# from webdriver_manager.chrome import ChromeDriverManager

import time
import json
from datetime import datetime
import os
import csv
import pandas as pd
# pip install openpyxl
# pip install xlsxwriter

from get_token import get_token_instance
from graphql_query_code import generate_graphql_query

import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


def get_token_with_retry(service, url, max_tries=5):
    attempt = 0
    while attempt < max_tries:
        auth_token = get_token_instance(service, url)
        if auth_token is not None:
            return auth_token
        else:
            logger.info("No authorization token received. Retrying...")
        attempt += 1
        time.sleep(2)
    return None


def set_query_variables(
    data: dict,
    category_id: str,
    offset: int = 0,
    limit: int = 1,
    showAdultContent: str = "TRUE",
    filters: list = None,
    sort: str = "BY_RELEVANCE_DESC",
    correctQuery: bool = False,
    getFastCategories: bool = True,
    fastCategoriesLevelOffset: int = 2,
    getPromotionItems: bool = True
) -> None:
    """
    Set query variables for the GraphQL query.

    Args:
        data (dict): The data dictionary to update with query variables.
        category_id (str): The category ID to query.
        offset (int): The pagination offset.
        limit (int): The pagination limit.
        showAdultContent (str): The adult content filter.
        filters (list): The filters to apply to the query.
        sort (str): The sort order for the results.
        correctQuery (bool): Whether to correct the query.
        getFastCategories (bool): Whether to get fast categories.
        fastCategoriesLevelOffset (int): The level offset for fast categories.
        getPromotionItems (bool): Whether to get promotion items.

    Returns:
        None
    """
    if filters is None:
        filters = []

    data["variables"]["queryInput"]["categoryId"] = category_id
    data["variables"]["queryInput"]["pagination"]["offset"] = offset
    data["variables"]["queryInput"]["pagination"]["limit"] = limit
    data["variables"]["queryInput"]["showAdultContent"] = showAdultContent
    data["variables"]["queryInput"]["filters"] = filters
    data["variables"]["queryInput"]["sort"] = sort
    data["variables"]["queryInput"]["correctQuery"] = correctQuery
    data["variables"]["queryInput"]["getFastCategories"] = getFastCategories
    data["variables"]["queryInput"]["fastCategoriesLevelOffset"] = fastCategoriesLevelOffset
    data["variables"]["queryInput"]["getPromotionItems"] = getPromotionItems


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
        print(f'Data saved to {filename}.xlsx\n')
    except Exception as e:
        logger.error(f"Error in saving to .xlsx file: {e}")


def check_response_with_retry(response: dict) -> bool:
    if response is not None:
        if 'errors' in response:
            unauthorized = any(
                error.get('extensions', {}).get('code') == 'UNAUTHORIZED' or
                error.get('message') == 'Unauthorized'
                for error in response['errors']
            )
            if unauthorized:
                print(
                    "Error: Authorization token is declined. Getting a new token...")
                auth_token = get_token_with_retry(service, main_url)
                if auth_token is None:
                    print("Can't retrieve authorization token! Shutting down...")
                    return False
            else:
                print("Errors in response:", response['errors'])
                return False
        else:
            return True
    else:
        logger.error("No response received or an error occurred.")
        return False


main_url = "https://uzum.uz/ru"
graphql_url = "https://graphql.uzum.uz/"
category_id = "12690"
data_dir = "data"

try:
    chrome_options = webdriver.ChromeOptions()

    # service = Service(ChromeDriverManager().install())
    service = Service()

    auth_token = get_token_with_retry(service, main_url)
    if auth_token is None:
        print("Can't retrieve authorization token! Shutting down...")
        exit()

    driver = uc.Chrome(service=service, options=chrome_options)

    # # Load the data dictionary from the JSON file
    # with open('graphql_query_data.json', 'r', encoding='utf-8') as json_file:
    #     payload_json = json.load(json_file)

    payload_json = generate_graphql_query()

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # Run first query to get variables values and check connection
    set_query_variables(payload_json, category_id, 0,
                        0, sort="BY_ORDERS_NUMBER_DESC")
    js_code = generate_fetch_js_code(payload_json, auth_token, graphql_url)

    driver.get(main_url)
    WebDriverWait(driver, 20).until(EC.title_contains("Uzum Market"))

    print(f"PAGE LOADED: {driver.title}")
    driver.execute_script(js_code)

    WebDriverWait(driver, 20).until(lambda d: d.execute_script(
        "return window.graphqlResponse") is not None)
    response = driver.execute_script("return window.graphqlResponse;")

    if check_response_with_retry(response):
        is_done = False
        category_name = response["data"]["makeSearch"]["category"]["title"]
        total_items = response["data"]["makeSearch"]["total"]
        items_collected = 0
        items_offset = 0
    else:
        is_done = True

    data_list = []

    while not is_done:
        set_query_variables(payload_json, category_id,
                            items_offset, 100, sort="BY_ORDERS_NUMBER_DESC")

        js_code = generate_fetch_js_code(payload_json, auth_token, graphql_url)

        driver.get(main_url)
        WebDriverWait(driver, 20).until(EC.title_contains("Uzum Market"))

        driver.execute_script(js_code)

        WebDriverWait(driver, 20).until(lambda d: d.execute_script(
            "return window.graphqlResponse") is not None)
        response = driver.execute_script("return window.graphqlResponse;")

        if check_response_with_retry(response):
            data_list.extend(get_data_from_json(response))
            items_collected = len(data_list)
            items_offset += min(100, total_items - items_collected)
            print(f'Collected {items_collected} of total {
                  total_items} items in {category_name}.')
        else:
            break

        if items_collected >= total_items:
            print('Finished collecting.')
            is_done = True

    if len(data_list) != 0:
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")

        # json_file_name = os.path.join(
        #     data_dir, f'{category_name}_{current_time}.json')
        csv_file_name = os.path.join(
            data_dir, f'{category_name}_{current_time}.csv')
        excel_file_name = os.path.join(
            data_dir, f'{category_name}_{current_time}')

        # # Save JSON response
        # with open(json_file_name, 'w', encoding='utf-8') as json_file:
        #     json.dump(response, json_file,
        #                 indent=4, ensure_ascii=False)
        # print(f"Response saved to {json_file_name}")

        # Save data_list to CSV with BOM
        keys = data_list[0].keys() if data_list else []
        with open(csv_file_name, 'w', newline='', encoding='utf-8-sig') as csv_file:
            dict_writer = csv.DictWriter(csv_file, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(data_list)
        print(f"Data saved to {csv_file_name}")

        save_excel(data_list, excel_file_name)
    else:
        print(f"No items collected from category {category_name}")

except Exception as e:
    logger.error(f"Error in driver: {e}")
finally:
    try:
        driver.quit()
    except Exception as e:
        logger.error(f"Error during driver quit: {e}")
