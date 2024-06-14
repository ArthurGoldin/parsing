import scrapy
from selenium import webdriver
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class UzumSpider(scrapy.Spider):
    name = 'uzum_spider'
    start_urls = ['https://uzum.uz/ru']

    def __init__(self, *args, **kwargs):
        super(UzumSpider, self).__init__(*args, **kwargs)
        self.init_driver()

    def init_driver(self):
        options = webdriver.ChromeOptions()
        service = Service(ChromeDriverManager().install())
        # options.add_argument('--headless')
        self.driver = uc.Chrome(options=options, service=service)

    def start_requests(self):
        print("------------------------------------------START REQUEST------------------------------------------")
        for url in self.start_urls:
            try:
                self.driver.get(url)
                # Wait for the page title to contain 'Uzum Market'
                WebDriverWait(self.driver, 20).until(
                    EC.title_contains('Uzum Market')
                )

                # Get the page source and create a Scrapy response
                page_source = self.driver.page_source
                response = scrapy.http.HtmlResponse(
                    url=url, body=page_source, encoding='utf-8')

                # Create a Scrapy request and pass the response in meta
                yield scrapy.Request(url=url, callback=self.parse, meta={'selenium_response': response})

            except (TimeoutException, WebDriverException) as e:
                self.logger.error(f"Error processing URL {url}: {e}")
                self.logger.error(f"Current page title: {
                                  self.driver.title if self.driver else 'N/A'}")
                self.restart_driver()
                continue

    def parse(self, response):
        # Extract data using Scrapy selectors
        # Get the Selenium HtmlResponse from the meta attribute
        selenium_response = response.meta['selenium_response']
        print("------------------------------------------PARSE REQUEST------------------------------------------")
        pass
        # title = response.css('selector_of_title::text').get()
        # price = response.css('selector_of_price::text').get()

        # # Yield the item
        # yield {
        #     'title': title,
        #     'price': price
        # }

    def restart_driver(self):
        self.driver.quit()
        self.init_driver()

    def closed(self, reason):
        self.driver.quit()
