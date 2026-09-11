# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

from dataclasses import dataclass
import scrapy

@dataclass
class CrawlerItem:
    # define the fields for your item here like:
    # name: str | None = None
    pass

class PageItems(scrapy.Item):
    url = scrapy.Field()
    html = scrapy.Field()
    depth = scrapy.Field()
    crawledAt = scrapy.Field()
    content_hash = scrapy.Field()
    cleaned_content = scrapy.Field()
    tables = scrapy.Field()
    is_pdf = scrapy.Field()
    source = scrapy.Field()
    entity = scrapy.Field()
    relevance_score = scrapy.Field()
    matched_terms = scrapy.Field()
    youtube_video = scrapy.Field()
    comments = scrapy.Field()