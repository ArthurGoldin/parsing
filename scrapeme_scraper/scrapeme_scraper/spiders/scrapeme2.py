from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor


class ScrapemeSpider(CrawlSpider):
    name = "scrapeme2"
    allowed_domains = ["scrapeme.live"]
    start_urls = ["https://scrapeme.live/shop/"]

    # crawling only the pagination pages, which have the
    # "https://scrapeme.live/shop/page/<number>/" format
    rules = (
        Rule(LinkExtractor(allow=r"shop/page/\d+/"),
             callback="parse", follow=True),
    )

    def parse(self, response):
        # get all HTML product elements
        products = response.css("li.product")
        # iterate over the list of products
        for product in products:
            # since the price elements contain several
            # text nodes
            price_text_elements = product.css(".price *::text").getall()
            price = "".join(price_text_elements)

            # return a generator for the scraped item
            yield {
                "name": product.css("h2::text").get(),
                "image": product.css("img").attrib["src"],
                "price": price,
                "url": product.css("a").attrib["href"],
            }
