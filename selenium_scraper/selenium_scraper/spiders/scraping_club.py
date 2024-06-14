from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains
from scrapy_selenium import SeleniumRequest
import scrapy
from selenium.webdriver.support.wait import WebDriverWait


class ScrapingClubSpider(scrapy.Spider):
    name = "scraping_club"

    def start_requests(self):
        url = "https://scrapingclub.com/exercise/list_infinite_scroll/"
        yield SeleniumRequest(url=url, callback=self.parse)

    def parse(self, response):
        driver = response.request.meta["driver"]

        # wait for 10 seconds for the 60th to be on the page
        wait = WebDriverWait(driver, timeout=10)
        wait.until(lambda driver: driver.find_element(
            By.CSS_SELECTOR, ".post:nth-child(60)").is_displayed())

        # scroll to the end of the page 10 times
        for x in range(0, 10):
            # scroll down by 10000 pixels
            ActionChains(driver) \
                .scroll_by_amount(0, 10000) \
                .perform()

        wait = WebDriverWait(driver, timeout=10)
        wait.until(lambda driver: driver.find_element(
            By.CSS_SELECTOR, ".post:nth-child(60)").is_displayed())

        # select all product elements and iterate over them
        for product in driver.find_elements(By.CSS_SELECTOR, ".post"):
            # scrape the desired data from each product
            url = product.find_element(
                By.CSS_SELECTOR, "a").get_attribute("href")
            image = product.find_element(
                By.CSS_SELECTOR, ".card-img-top").get_attribute("src")
            name = product.find_element(By.CSS_SELECTOR, "h4 a").text
            price = product.find_element(By.CSS_SELECTOR, "h5").text

            # add the data to the list of scraped items
            yield {
                "url": url,
                "image": image,
                "name": name,
                "price": price
            }
