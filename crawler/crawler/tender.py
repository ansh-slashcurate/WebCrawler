"""Local, free heuristics for finding/extracting bank tender & RFP listings.

Two jobs, kept deliberately separate from any LLM call (see
crawler/watsonx_client.py for the only place an LLM is used in this project):

  - tender_page_score(): a cheap keyword score used only to prioritize the
    crawl frontier toward tender/procurement pages and to recognize one.
    Fixed, not user-editable - it answers "is this a tender page at all",
    not "is this a tender I care about".
  - extract_tender_records(): pulls structured tender rows (title, reference
    no, dates, and every link found alongside them) out of a page's raw
    HTML. Extraction is unfiltered - every record found is returned with
    classification="pending"; a later, separate step decides relevance
    against a user's own tags.
"""
import datetime
import re
from collections import Counter
from urllib.parse import urljoin

from lxml import etree, html as lxml_html

# deliberately not imported from crawler.pipelines: that module imports this
# one (for TenderExtractionPipeline), so importing pipelines here too would
# create a circular import. Both of these are copied 1:1 from pipelines.py -
# keep them in sync if either changes there.


def _cell_text(cell):
    text = cell.text_content().replace("[at]", "@").replace("[dot]", ".")
    return re.sub(r"\s+", " ", text).strip()


def utc_timestamp():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

TENDER_PAGE_KEYWORDS = [
    "tender", "tenders", "procurement", "rfp", "request for proposal",
    "eoi", "expression of interest", "empanelment", "notice inviting tender", "nit",
]

_TENDER_PATTERNS = [
    (term, re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE))
    for term in TENDER_PAGE_KEYWORDS
]

# document extensions we consider a "download this RFP" link, vs. any other
# link on the row which is treated as a detail-page candidate instead. Never
# fetched (crawler.spiders.crawler.DENY_EXTENSIONS already excludes these) -
# only the URL itself is captured, per "collect links only, no download".
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx")

# canonical tender field -> header-cell substrings that identify that column.
# Best-effort: bank tender tables are wildly inconsistent, this will need
# tuning against real bank HTML rather than ever being exhaustive.
_COLUMN_HINTS = {
    "title": ["title", "subject", "description", "name of work", "work name", "particulars"],
    "reference_no": ["tender no", "ref no", "reference", "tender id", "nit no", "rfp no"],
    "published_date": ["published", "issue date", "date of issue", "start date", "posted"],
    "closing_date": ["due date", "closing date", "last date", "submission date", "end date", "deadline"],
}

_REFERENCE_RE = re.compile(r"(?:Tender|RFP|NIT)\s*(?:No\.?|Number|ID)[:\s]*([\w/-]{3,})", re.IGNORECASE)
_CLOSING_DATE_RE = re.compile(
    r"(?:Due|Closing|Last|Submission)\s*Date[:\s]*([\d/.\-A-Za-z, ]{6,25})", re.IGNORECASE
)


def tender_page_score(text):
    """Word-boundary keyword score against TENDER_PAGE_KEYWORDS - same
    approach as entity.EntityQuery.score. Used only for crawl-time link
    priority and to recognize a tender page; never shown to a user."""
    if not text:
        return 0
    return sum(len(pattern.findall(text)) for _, pattern in _TENDER_PATTERNS)


def _match_column(header_text):
    lower = header_text.lower()
    for field, hints in _COLUMN_HINTS.items():
        if any(hint in lower for hint in hints):
            return field
    return None


def _row_cells_with_links(tr, page_url):
    """Like pipelines._cell_text but keeps each cell's resolved-absolute
    hrefs too, since a tender table cell's document/detail link is exactly
    what pipelines.extract_tables (text-only) discards."""
    cells = []
    for cell in tr.xpath("./th|./td"):
        text = _cell_text(cell)
        hrefs = [urljoin(page_url, href) for href in cell.xpath(".//a/@href") if href]
        cells.append((text, hrefs))
    return cells


def _split_links(hrefs):
    document_links, other_links = [], []
    for href in hrefs:
        (document_links if href.lower().endswith(DOCUMENT_EXTENSIONS) else other_links).append(href)
    return document_links, other_links


def _extract_table_records(tree, page_url):
    records = []
    for table_el in tree.xpath("//table"):
        trs = table_el.xpath(".//tr")
        if not trs:
            continue

        rows = [_row_cells_with_links(tr, page_url) for tr in trs]
        widths = [len(cells) for cells in rows if len(cells) > 1]
        if not widths:
            continue
        mode_width = Counter(widths).most_common(1)[0][0]

        header_labels = None
        column_fields = None
        is_tender_table = False
        for cells in rows:
            if len(cells) != mode_width:
                continue
            texts = [text for text, _ in cells]
            if header_labels is None:
                header_labels = texts
                column_fields = [_match_column(t) for t in texts]
                # need >=2 recognized columns to trust this is a tender
                # listing and not some unrelated same-shaped table
                is_tender_table = sum(1 for f in column_fields if f) >= 2
                continue
            if not is_tender_table or not any(text for text, _ in cells):
                continue

            record = {"extra": {}}
            all_hrefs = []
            for (text, hrefs), field, head_label in zip(cells, column_fields, header_labels):
                all_hrefs.extend(hrefs)
                if field:
                    record[field] = text
                elif text:
                    record["extra"][head_label] = text

            if not record.get("title"):
                continue

            document_links, other_links = _split_links(all_hrefs)
            record["document_links"] = document_links
            record["detail_url"] = other_links[0] if other_links else None
            records.append(record)

    return records


def _page_heading(tree):
    heading_el = tree.xpath("//h1|//h2")
    return _cell_text(heading_el[0]) if heading_el else ""


def _extract_fallback_record(tree, page_url, page_text, title):
    """No qualifying table on this page - if it reads as a genuine single
    tender detail page, emit one record from its own heading instead of
    giving up empty-handed."""
    ref_match = _REFERENCE_RE.search(page_text)
    closing_match = _CLOSING_DATE_RE.search(page_text)
    hrefs = [urljoin(page_url, href) for href in tree.xpath("//a/@href") if href]
    document_links, _ = _split_links(hrefs)

    return {
        "title": title,
        "reference_no": ref_match.group(1).strip() if ref_match else None,
        "published_date": None,
        "closing_date": closing_match.group(1).strip() if closing_match else None,
        "document_links": document_links,
        "detail_url": page_url,
        "extra": {},
    }


def extract_tender_records(html, page_url):
    """Best-effort structural extraction only - no topical filtering here
    (see module docstring). Returns a list of plain dicts ready to attach to
    a PageItems' tender_records field; each is unfiltered/unclassified."""
    try:
        tree = lxml_html.fromstring(html)
    except (etree.ParserError, ValueError):
        return []

    records = _extract_table_records(tree, page_url)

    if not records:
        heading_text = _page_heading(tree)
        # Require the HEADING ITSELF to read as tender-related, not just the
        # page's URL or its full text. Scoring the whole page (as this used
        # to do) false-positives on any page with a "Tenders" nav link
        # anywhere in its header/footer chrome - confirmed against a real
        # PNB Bank crawl, whose generic homepage promo banner heading got
        # misfiled as a "tender" 382 times, every stored record identical
        # junk. Scoring the URL alone isn't enough either: PNB's own
        # /Tender.aspx page has a "tender"-matching URL but its <h1> is that
        # same generic banner (its real tender titles sit inside an
        # ASP.NET postback control, not a heading at all) - trusting the URL
        # there would still emit one wrong record per such page. Better to
        # emit nothing than a title we don't actually trust.
        if heading_text and tender_page_score(heading_text) > 0:
            page_text = tree.text_content()
            fallback = _extract_fallback_record(tree, page_url, page_text, heading_text)
            if fallback:
                records = [fallback]

    for record in records:
        record["source_url"] = page_url
        record["extracted_at"] = utc_timestamp()
        record["classification"] = "pending"
        record["matched_tags"] = []
        record["reason"] = None

    return records
