import requests
from datetime import datetime
import json
import time
import re
from bs4 import BeautifulSoup
from selenium import webdriver
# import pathlib


def get_auth_token():
    # URL that includes the HTML/JavaScript with the token
    page_url = 'https://uzum.uz/ru'

    # Define a generic regex pattern for common token names
    token_patterns = [
        r"var token = '([^']+)'",  # var token = '...'
        r"var authToken = '([^']+)'",  # var authToken = '...'
        r"var accessToken = '([^']+)'",  # var accessToken = '...'
        # "accessToken": "..."
        r"['\"]accessToken['\"]:\s*['\"]([^'\"]+)['\"]",
        r"['\"]token['\"]:\s*['\"]([^'\"]+)['\"]"  # "token": "..."
    ]

    driver = webdriver.Chrome()  # Or another browser driver

    driver.get(page_url)

    # Wait for JavaScript to load and execute
    driver.implicitly_wait(1000)  # Adjust time based on expected delay

    # Get page source after JavaScript execution
    page_source = driver.page_source

    # Parse the source with BeautifulSoup
    soup = BeautifulSoup(page_source, 'html.parser')
    script_texts = soup.find_all('script')
    found_token = None

    for script in script_texts:
        if script.string:
            for pattern in token_patterns:
                match = re.search(pattern, script.string)
                if match:
                    found_token = match.group(1)
                    break
        if found_token:
            break

    driver.quit()

    if found_token:
        print("Found token:", found_token)
    else:
        print("Token not found in dynamically loaded content.")


def fetch_root_catalog_uzum():
    url = "https://api.uzum.uz/api/main/root-categories?eco=false"

    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'ru-RU',
        'Authorization': 'eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE0OTI1ODc5LCJzdWIiOiIyMzU3NDM1NS1lODcwLTRjODktODk3ZS00MjZmYjBiZTg1ZTIiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTQ5MjY1OTl9.CPzmAtu0w3m_BnLykMpvy7qg1CoBaf1jKY9esj3F7a6uCBCHFrQR5PzHp5jSxsazWtZi3C5LBkAZHu52do8zBA'
    }

    response = requests.get(url, headers=headers)

    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    if response.status_code == 200:
        print("Root catalog data retrieved successfully!")
        print(response.headers['Content-Type'])
        with open('uzum_root_catalog.json', 'w', encoding='UTF-8') as file:
            json.dump(response.json(), file, indent=4, ensure_ascii=False)
        return response.json()
    else:
        print(f"Failed to fetch data. Status code: {response.status_code}")
        print(response.text)


def get_category_data():
    url = "https://graphql.uzum.uz/"

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': 'eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE2MjAyMTc1LCJzdWIiOiJjODdiZmJkNC01Y2ZjLTQ1NWUtOTdmNy04NWMxNDI0MzI3MWYiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTYyMDI4OTV9.NNtJ3S0Jm1BytHVss4n7eOdRdzr6chGBssdOFxEGNJ7MnZWqd1jqQDX3Ie6A9iDDa2-0Q2dap3_MkglgojoBBw',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    }

    query = """
        query getMakeSearch($queryInput: MakeSearchQueryInput!) {
        makeSearch(query: $queryInput) {
            id
            queryId
            queryText
            category {
                id
                title
                __typename
            }
            items {
                catalogCard {
                    id
                    title
                    minSellPrice
                    __typename
                }
                __typename
            }
            total
            __typename
        }
    }
    """
    variables = {
        "queryInput": {
            "categoryId": "10398",
            "showAdultContent": "NONE",
            "filters": [],
            "sort": "BY_RELEVANCE_DESC",
            "pagination": {
                "offset": 0,
                "limit": 1
            },
            "correctQuery": False,
            "getFastCategories": True,
            "fastCategoriesLimit": 11,
            "fastCategoriesLevelOffset": 2,
            "getPromotionItems": True
        }
    }

    payload = {
        'query': query,
        'variables': variables
    }

    def is_response_valid(response):
        # This function checks both rate limiting and general errors.
        if 'errors' in response:
            for error in response['errors']:
                if error.get('extensions', {}).get('http', {}).get('status') in [429, 503]:
                    return False
        return True

    def send_request_with_retry(url, headers, payload, max_retries=0):
        session = requests.Session()  # Using session for connection reuse
        attempt = 0
        while attempt < max_retries:
            try:
                response = session.post(
                    url, headers=headers, data=json.dumps(payload))
                response.raise_for_status()  # Handles all bad HTTP statuses as exceptions

                response_data = response.json()

                if is_response_valid(response_data):
                    return response_data
                else:
                    print("Response validation failed. Retrying...")

            except requests.exceptions.HTTPError as e:
                print(f"HTTP Error: {e}")
            except requests.exceptions.RequestException as e:
                print(f"Network Error: {e}")

            attempt += 1
            wait_time = min(2 ** attempt, 30)  # Using a cap on wait time
            print(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

        print("Max retries reached. Failed to fetch data.")

        response = session.post(
            url, headers=headers, data=json.dumps(payload))

        print(f"Failed to fetch data. Status code: {response.status_code}")

        if response.headers['Content-Type'] != 'application/json':
            print("Non-JSON response received")
        print(response.text)

        return None

    data = send_request_with_retry(url, headers, payload)

    if data:
        # Print the raw JSON response for debugging
        print(json.dumps(data, indent=2))

        # Check for errors in the response
        if 'errors' in data:
            print("Errors in the response:", data['errors'])
        else:
            # Extract the data from the response
            print("Data successfully written to products.csv")
    else:
        print("Failed to fetch data after multiple retries.")

    # response = requests.post(url, headers=headers, data=json.dumps(payload))

    # if response.status_code == 200:
    #     print("Data fetched")
    #     data = response.json()
    #     if 'errors' in data:
    #         print("Errors in the response:", data['errors'])
    #     else:
    #         products = data['data']['products']

    # else:
    #     print(f"Failed to fetch data. Status code: {response.status_code}")
    #     print(response.text)


if __name__ == '__main__':
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    print('Trying parser...')
    # root_catalog = fetch_root_catalog_uzum()
    get_category_data()
    # auth_token = get_auth_token()
