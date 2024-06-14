import scrapy
from selenium import webdriver
from scrapy.http import JsonRequest
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class UzumscraperSpider(scrapy.Spider):
    name = 'uzum'
    graphql_url = 'https://uzum.uz/ru'
    custom_settings = {
        'DOWNLOAD_DELAY': 1,  # Add a delay between requests
        'RETRY_TIMES': 5,  # Retry up to 5 times on failure
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }

    def start_requests(self):
        options = Options()
        options.headless = True  # Run Chrome in headless mode (without GUI)
        driver = webdriver.Chrome()

        driver.get('https://uzum.uz/ru')  # Replace with the actual URL
        token = driver.execute_script(
            "return localStorage.getItem('auth_token');"
        )
        # Clean up and close the browser
        driver.quit()

        if token:
            print(
                "------------------------------------GOT THE TOKEN--------------------------------")
            self.settings.set('AUTH_TOKEN', token)  # Store token in settings
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': 'eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE2MjA0NzY5LCJzdWIiOiJjODdiZmJkNC01Y2ZjLTQ1NWUtOTdmNy04NWMxNDI0MzI3MWYiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTYyMDU0ODl9.HAbKLlgCs-kAZRzd2LW7u8UshoLpzUsf_QicmHjUL4oV8tmG833RbE4pOZs1zbMUwbgA992gHSvgpQB2r0kUAQ',
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
            print(
                "BEFORE YEILD!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            yield JsonRequest(
                url=self.graphql_url,
                data=payload,
                headers=headers,
                callback=self.parse_graphql_response,
                errback=self.handle_errors,  # Add error handling
                dont_filter=True  # Prevent request from being filtered
            )
        else:
            self.logger.error("Failed to retrieve authorization token.")

    def parse_graphql_response(self, response):
        print("INSIDE parse_graphql_response!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        if response.status == 200:
            data = response.json()
            if 'errors' in data:
                self.logger.error(f"Errors in the response: {data['errors']}")
            else:
                make_search = data['data']['makeSearch']
                for item in make_search['items']:
                    yield {
                        'id': make_search['id'],
                        'queryId': make_search['queryId'],
                        'queryText': make_search['queryText'],
                        'category_id': make_search['category']['id'],
                        'category_title': make_search['category']['title'],
                        'item_id': item['catalogCard']['id'],
                        'item_title': item['catalogCard']['title'],
                        'item_price': item['catalogCard']['minSellPrice']
                    }
        else:
            self.logger.error(f"Failed to fetch data. Status code: {
                              response.status}")

    def handle_errors(self, failure):
        self.logger.error(f"Request failed with: {failure}")
