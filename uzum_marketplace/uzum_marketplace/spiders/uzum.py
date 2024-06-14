import scrapy


class UzumSpider(scrapy.Spider):
    name = "uzum_spider"
    allowed_domains = ["uzum.uz"]
    start_urls = ["https://uzum.uz/ru/"]

    def parse(self, response):
        print(response.text)
        pass
        # title = self.response.css('title::text').get()
        # yield {
        #     'title': title
        # }

        # products = response.css(".product")
        # for product in products:
        #     price_text_elements = product.css(".price *::text").getall()
        #     price = "".join(price_text_elements)

        #     yield {
        #         "name": product.css("h2::text").get(),
        #         "image": product.css("img").attrib["src"],
        #         "price": price,
        #         "url": product.css("a").attrib["href"],
        #     }

        # pagination_link_elements = response.css("a.page-numbers")

        # for pagination_link_element in pagination_link_elements:
        #     pagination_link_url = pagination_link_element.attrib["href"]
        #     if pagination_link_url:
        #         yield scrapy.Request(
        #             response.urljoin(pagination_link_url)
        #         )
