# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import json
from pathlib import Path
import os
import redis
import hashlib

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem
import trafilatura

class CrawlerPipeline:
    def process_item(self, item):
        return item

# content hashpipeline

class ContentDedupPipeline:
    def __init__(self, redis_url):
        self.redis_url = redis_url
        self.client = None
 
    @classmethod
    def from_crawler(cls, crawler):
        return cls(redis_url=crawler.settings.get("REDIS_URL", "redis://localhost:6379/0"))
 
    def open_spider(self, spider):
        self.client = redis.from_url(self.redis_url)
 
    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        content_hash = hashlib.sha256(adapter["html"].encode("utf-8")).hexdigest()
 
        # SADD returns 0 if the member already existed - atomic, so two
        # workers hashing the same content at the same instant can't both
        # think they're first.
        is_new = self.client.sadd("content_hashes", content_hash)
        if not is_new:
            raise DropItem(f"Duplicate content: {adapter['url']}")
 
        adapter["content_hash"] = content_hash
        return item
    

# storage pipeline
class StoragePipeline:
    def __init__(self,output_dir):
        self.output_dir = output_dir
        self.out_file = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(output_dir=crawler.settings.get("OUTPUT_DIR", "output"))

        
    def open_spider(self, spider):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        out_path = os.path.join(self.output_dir, f"pages.jsonl")
        self.out_file = open(out_path, "a", encoding="utf-8")

        clean_path = os.path.join(self.output_dir, f"clean.jsonl")
        self.clean_file = open(clean_path, "a", encoding="utf-8")


    def close_spider(self, spider):
        if self.out_file:
            self.out_file.close()
        if self.clean_file:
            self.clean_file.close()


    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        record = {
            "url": adapter.get("url"),
            "html": adapter.get("html"),
            "depth": adapter.get("depth"),
            "crawledAt": adapter.get("crawledAt"),
            "content_hash": adapter.get("content_hash"),
        }

        # cleaning the html content using trafilatura, written to its own file
        cleaned_content = trafilatura.extract(record["html"])

        if not cleaned_content:
            return item

        self.out_file.write(json.dumps(record, ensure_ascii=False) + "\n")

        clean_record = {
            "url": record["url"],
            "cleaned_content": cleaned_content,
        }
        self.clean_file.write(json.dumps(clean_record, ensure_ascii=False) + "\n")

        return item

    