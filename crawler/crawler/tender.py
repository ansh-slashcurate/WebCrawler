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
import logging
import re
from collections import Counter
from urllib.parse import urljoin

from lxml import etree, html as lxml_html

logger = logging.getLogger(__name__)

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
# Best-effort: bank tender tables are wildly inconsistent. Dict order no
# longer matters for matching (see _match_column) - "tender"/"rfp" appear
# almost everywhere on a tender page's own header row (Tender No, Tender
# Date, RFP No, ...), so they're deliberately NOT listed here as bare words
# for any field; a bare generic word would win a column it has no business
# winning purely by being checked first. Add more specific phrases (e.g.
# "tender date", not "tender") when tuning against a new bank instead.
_COLUMN_HINTS = {
    "title": ["title", "subject", "name of work", "work name", "particulars"],
    "office": [
        "office", "branch", "circle", "zone", "region", "location", "department",
        "issued by", "issuing authority", "issuing department",
    ],
    "description": [
        "description of tender", "description of work", "tender description",
        "description", "details", "detail", "scope of work",
    ],
    "reference_no": [
        "tender no", "ref no", "reference no", "reference", "tender id",
        "nit no", "rfp no", "bid no", "enquiry no",
    ],
    "published_date": [
        # "publication date" is NOT a substring of "publish(ed) date" -
        # confirmed live: UCO Bank's own 379-row tender table uses
        # "Publication Date" as its header, which matched nothing here
        # before, leaving only 1 recognized column (below the 2-column
        # trust threshold) and silently rejecting the entire real table
        "published date", "publish date", "publication date", "date of publication",
        "issue date", "date of issue", "start date", "posted", "tender date",
        "opening date", "open date",
    ],
    "closing_date": [
        "due date", "closing date", "last date", "submission date",
        "end date", "deadline", "bid closing",
    ],
}

_REFERENCE_RE = re.compile(r"(?:Tender|RFP|NIT)\s*(?:No\.?|Number|ID)[:\s]*([\w/-]{3,})", re.IGNORECASE)
# a real date value only - deliberately NOT the old open-ended
# "[\d/.\-A-Za-z, ]{6,25}" character class, which (confirmed against a real
# PNB row) bleeds straight through a following label like "End Date" when
# the two sit close together in the same combined cell (e.g. "...10:00 AM
# End Date :29-Sep-2026...") since spaces/letters/digits are all still
# inside that class with nothing to stop it early
_DATE_VALUE_RE = (
    r"(?:\d{1,2}[\s./-][A-Za-z]{3,9}[\s./-]\d{2,4}|\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
    r"(?:\s+\d{1,2}:\d{2}\s*[APap][Mm]?)?"
)
# tolerates filler phrasing between a date label and its actual value, not
# just a bare colon/space - confirmed live: Bank of Maharashtra labels its
# closing date "Last date OF SUBMISSION: 13/10/2026", not just "Last Date:"
_DATE_LABEL_CONNECTOR = r"[:\s]*(?:of\s+\w+)?[:\s]*"
# each label is a single non-capturing alternation covering both word
# orders a bank might use ("Commencement Date" vs "Date of Commencement",
# confirmed live on Bank of Maharashtra for the latter) so there's still
# only one capture group (the value) regardless of which order matched -
# every caller of these two regexes already just reads match.group(1)
_PUBLISHED_LABEL = (
    r"(?:(?:Publish(?:ed)?|Commencement|Issue|Start|Posted|Open(?:ing)?)\s*Date"
    r"|Date\s+of\s+(?:Commencement|Issue|Publication|Posting))"
)
_PUBLISHED_DATE_RE = re.compile(rf"{_PUBLISHED_LABEL}{_DATE_LABEL_CONNECTOR}({_DATE_VALUE_RE})", re.IGNORECASE)
# "End" added alongside the original Due/Closing/Last/Submission set - PNB's
# own tender table (confirmed from a live crawl) labels this "End Date",
# which none of those matched
_CLOSING_LABEL = (
    r"(?:(?:Due|Closing|Last|Submission|End)\s*Date"
    r"|Date\s+of\s+(?:Closing|Submission|Expiry))"
)
_CLOSING_DATE_RE = re.compile(rf"{_CLOSING_LABEL}{_DATE_LABEL_CONNECTOR}({_DATE_VALUE_RE})", re.IGNORECASE)


def tender_page_score(text):
    """Word-boundary keyword score against TENDER_PAGE_KEYWORDS - same
    approach as entity.EntityQuery.score. Used only for crawl-time link
    priority and to recognize a tender page; never shown to a user."""
    if not text:
        return 0
    return sum(len(pattern.findall(text)) for _, pattern in _TENDER_PATTERNS)


# deliberately \d{1,3}, not \d{1,4} - confirmed live: Bank of Maharashtra's
# tender page also has year-FILTER links (2026, 2025, 2024, ...), which are
# a different, non-overlapping VIEW of the listing, not "the next page" of
# it, yet a bare "2026" matches a page-number pattern just as easily. A real
# tender listing realistically never has 1000+ pages, so restricting to 3
# digits excludes every calendar year while still matching any plausible
# page number. Getting this wrong is expensive: this text also grants the
# spider's pagination hop its exemption from max_depth, so misclassifying a
# year filter as pagination let it (and the full page-1/2/3/4 pagination
# each year view repeats) branch out combinatorially - confirmed live, one
# crawl produced 2770 tender records for a bank whose own listing shows a
# total of 256.
_PAGINATION_TEXT_RE = re.compile(
    r"^(?:\d{1,3}|next|prev(?:ious)?|first|last|»|«|›|‹|>>|<<)$", re.IGNORECASE
)
_PAGINATION_URL_RE = re.compile(r"(?:[?&](?:page|pg|p)=\d+|/page/\d+|pageno=\d+)", re.IGNORECASE)


def looks_like_pagination_link(link_text, link_url):
    """True for a link that's plausibly a "next page"/page-number control on
    a tender listing, rather than unrelated site navigation - used by the
    spider's tender_mode link filter to let real pagination through even
    when its anchor text/URL carries no tender keyword of its own."""
    text = (link_text or "").strip()
    if text and _PAGINATION_TEXT_RE.match(text):
        return True
    return bool(_PAGINATION_URL_RE.search(link_url or ""))


def _match_column(header_text):
    """Whichever hint matches is the LONGEST (most specific) one across every
    field, not whichever field happens to come first in _COLUMN_HINTS - a
    generic short hint (e.g. "issue date") must never beat a more specific
    one (e.g. "tender date") just because its field was checked earlier.
    This is what makes adding hints for a new bank safe: a new, more
    specific phrase can only ever win a column away from a shorter, vaguer
    one, never the reverse - so tuning for one bank can't silently break a
    column that already worked for another."""
    lower = header_text.lower()
    best_field, best_len = None, 0
    for field, hints in _COLUMN_HINTS.items():
        for hint in hints:
            if len(hint) > best_len and hint in lower:
                best_field, best_len = field, len(hint)
    return best_field


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
    """Splits real http(s) links into document vs. detail-page candidates -
    a javascript:__doPostBack(...) href (confirmed live: PNB's own tender
    rows link this way) isn't a fetchable page at all, so it must never be
    stored as a detail_url a later step might try to crawl."""
    document_links, other_links = [], []
    for href in hrefs:
        if not href.lower().startswith(("http://", "https://")):
            continue
        (document_links if href.lower().endswith(DOCUMENT_EXTENSIONS) else other_links).append(href)
    return document_links, other_links


def _derive_title(text):
    """Best-effort title for a combined-cell row (e.g. one "Detail" column
    carrying the tender's title plus inline "Publish Date"/"End Date" text,
    as PNB's table does) - cut the text at whichever recognized field regex
    matches earliest, since everything from that point on is metadata, not
    part of the title."""
    cut = len(text)
    for pattern in (_PUBLISHED_DATE_RE, _CLOSING_DATE_RE, _REFERENCE_RE):
        match = pattern.search(text)
        if match:
            cut = min(cut, match.start())
    title = text[:cut].strip(" .:-")
    return title or text[:150].strip()


def _backfill_dates_and_title(record):
    """No-op for a bank whose table has real, separately-recognized title/
    date columns. For a bank that instead crams everything into one
    "description"-like column (PNB's "Detail" column, confirmed live),
    regex-split the combined text so the row isn't lost or reduced to a
    page-wide, single-record fallback (see extract_tender_records)."""
    description = record.get("description")
    if not description:
        return

    if not record.get("published_date"):
        match = _PUBLISHED_DATE_RE.search(description)
        if match:
            record["published_date"] = match.group(1).strip()

    if not record.get("closing_date"):
        match = _CLOSING_DATE_RE.search(description)
        if match:
            record["closing_date"] = match.group(1).strip()

    if not record.get("reference_no"):
        match = _REFERENCE_RE.search(description)
        if match:
            record["reference_no"] = match.group(1).strip()

    if not record.get("title"):
        record["title"] = _derive_title(description)


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

        same_width_rows = [cells for cells in rows if len(cells) == mode_width]
        if len(same_width_rows) < 2:
            continue

        header_labels = [text for text, _ in same_width_rows[0]]
        column_fields = [_match_column(t) for t in header_labels]
        data_rows = same_width_rows[1:]

        # need >=2 recognized columns to trust this is a tender listing and
        # not some unrelated same-shaped table
        recognized_count = sum(1 for f in column_fields if f)
        is_tender_table = recognized_count >= 2
        if not is_tender_table and recognized_count == 1:
            # a real, if sparse, listing can have no recognizable date
            # column at all - confirmed live: IOB's own notices table is
            # just "Sr. No. | Title | Action", no dates anywhere. Trust a
            # lone recognized title/description column anyway, but only
            # when the table's own row content actually reads as
            # tender-related - otherwise an unrelated single-column list
            # elsewhere on the page (e.g. a "Quick Links" table) would
            # qualify too, just for happening to have a "Title" header
            lone_field = next(f for f in column_fields if f)
            if lone_field in ("title", "description"):
                combined_text = " ".join(text for cells in data_rows for text, _ in cells)
                is_tender_table = tender_page_score(combined_text) > 0

        if not is_tender_table:
            continue

        for cells in data_rows:
            if not any(text for text, _ in cells):
                continue

            record = {"extra": {}}
            all_hrefs = []
            for (text, hrefs), field, head_label in zip(cells, column_fields, header_labels):
                all_hrefs.extend(hrefs)
                if field and field not in record:
                    record[field] = text
                elif text:
                    # either an unrecognized column, or a second column that
                    # matched a field an earlier column already filled - keep
                    # the text instead of silently overwriting/dropping it
                    record["extra"][head_label] = text

            _backfill_dates_and_title(record)
            if not record.get("title"):
                continue

            document_links, other_links = _split_links(all_hrefs)
            record["document_links"] = document_links
            record["detail_url"] = other_links[0] if other_links else None
            records.append(record)

    return records


_ID_ROW_INDEX_RE = re.compile(r"^(.*)_(\d+)$")
# stops at the next underscore deliberately (alnum only, no "_") - an
# ASP.NET auto id like "..._rptGrid_lblpagid_0" must resolve to "rptGrid",
# not "rptGrid_lblpagid" (which would differ per field and never group a
# row's fields together at all)
_REPEATER_NAME_RE = re.compile(r"(rpt[A-Za-z0-9]+|grd[A-Za-z0-9]+|lst[A-Za-z0-9]+)")
_ID_FIELD_LIKE_RE = re.compile(r"(lbl|lnk|lbtn|label|grid)", re.IGNORECASE)


def _extract_repeater_records(tree, page_url):
    """Fallback for a bank whose tender listing isn't a <table> at all but
    an ASP.NET WebForms Repeater/ListView (confirmed live on PNB's own
    Tender.aspx: rows render as separate <span>/<a> elements like
    ..._rptGrid_Label1_0 (office), ..._rptGrid_lbtnTenderTitle_0 (title,
    itself a __doPostBack link - not a real fetchable detail page),
    ..._rptGrid_lblTenCatName_0 (Publish Date) - never a single <tr>).

    ASP.NET names every Repeater item's child controls with the same
    trailing "_<row index>" regardless of which bank's page it is, so rows
    are grouped by that shared index instead of by table structure. Only
    the first repeater name encountered is kept: PNB (and presumably other
    bilingual bank sites) renders a second, differently-worded copy of the
    same rows for its Hindi toggle (id prefix "rptGrid1") right after the
    English ones - grouping by index alone would otherwise merge an
    English row and its unrelated Hindi counterpart into one garbled
    record just because both end in "_0".
    """
    rows = {}
    primary_repeater = None
    for el in tree.xpath("//*[@id]"):
        match = _ID_ROW_INDEX_RE.match(el.get("id") or "")
        if not match:
            continue
        prefix, index = match.groups()
        if not _ID_FIELD_LIKE_RE.search(prefix):
            continue
        repeater_match = _REPEATER_NAME_RE.search(prefix)
        if not repeater_match:
            continue
        repeater_name = repeater_match.group(1)
        if primary_repeater is None:
            primary_repeater = repeater_name
        if repeater_name != primary_repeater:
            continue
        rows.setdefault(index, []).append(el)

    records = []
    for _, elements in sorted(rows.items(), key=lambda kv: int(kv[0])):
        # order matters and is trusted as document order (xpath already
        # returns elements that way): whichever element is the row's own
        # <a> link is treated as the title, since a clickable title is the
        # near-universal shape for this kind of listing; text before it
        # (minus a bare serial number) is treated as office/category, text
        # after it as the date/description block - matching PNB's own
        # column order (S.No, Office, Detail) without needing to know its
        # specific control id names, which won't generalize to another bank
        title_index = next((i for i, el in enumerate(elements) if el.tag == "a"), None)
        if title_index is None:
            continue

        before = [_cell_text(el) for el in elements[:title_index]]
        before = [t for t in before if t and not t.isdigit()]
        after = [_cell_text(el) for el in elements[title_index + 1:]]

        record = {"extra": {}, "title": _cell_text(elements[title_index])}
        if before:
            record["office"] = " ".join(before)
        description = " ".join(t for t in after if t)
        if description:
            record["description"] = description

        _backfill_dates_and_title(record)
        if not (record.get("published_date") or record.get("closing_date")):
            # no recognizable date near this <a> - too weak a signal to
            # trust this is a real tender row and not unrelated page chrome
            # that happens to share the same id-numbering convention
            continue

        # a row's own title link is frequently another __doPostBack call
        # (PNB's opens a detail view that way, not a real URL) rather than a
        # fetchable page - _split_links already drops anything that isn't a
        # real http(s) link, same as the <table> extraction path above
        hrefs = [urljoin(page_url, el.get("href")) for el in elements if el.get("href")]
        document_links, other_links = _split_links(hrefs)
        record["document_links"] = document_links
        record["detail_url"] = other_links[0] if other_links else None
        records.append(record)

    return records


# a title link's own text is almost never this short for a real tender row -
# below this, it's virtually always a nav item, "read more"/"view" link, or
# a social icon's accessible-name text picked up by mistake
_MIN_CARD_TITLE_LEN = 15


def _extract_card_records(tree, page_url):
    """Fallback for a bank whose tender listing is neither a <table> nor an
    ASP.NET-style numbered-id repeater, but a plain repeating block of
    semantically-classed HTML - confirmed live on two different real banks
    with two different shapes: Bank of Maharashtra's title lives in the
    row's own <a href> (a <div class="searchContent"> with two sibling
    "label: value" date divs), while Union Bank of India's title is a bare
    <h2>, with dates as separate label/value <p> pairs and the row's real
    link sitting elsewhere in the same card as a plain "Know More" anchor.
    Neither has a <table> or a shared numbered id anywhere.

    Detected structurally rather than by class name (a specific bank's own
    class names won't generalize to another bank's markup): find every
    <a>/<h1-4> whose own text reads like a real title, then check whether
    its immediate PARENT's full text also contains a recognizable
    published-date AND closing-date pattern - if both are present, that
    parent is one tender row's whole container. The detail link, if any, is
    taken separately from anywhere in that same container, since the title
    element itself isn't always the one carrying it.
    """
    records = []
    # a plain list checked by identity (`is`), not id(container) in a set -
    # lxml element proxies are created lazily and can be garbage-collected
    # between loop iterations, and CPython is free to reuse a just-freed
    # object's id() for the very next allocation. Confirmed live: on Union
    # Bank of India's own page, that silently turned "already seen" into a
    # false positive for most containers, one iteration after the next,
    # dropping 8 of 10 real tenders instead of 0. Keeping the elements
    # themselves alive here is what actually prevents the id() reuse.
    seen_containers = []
    for el in tree.xpath("//a[@href] | //h1 | //h2 | //h3 | //h4"):
        title = _cell_text(el)
        if len(title) < _MIN_CARD_TITLE_LEN:
            continue

        container = el.getparent()
        if container is None or any(container is seen for seen in seen_containers):
            continue

        container_text = _cell_text(container)
        if not (_PUBLISHED_DATE_RE.search(container_text) and _CLOSING_DATE_RE.search(container_text)):
            continue
        seen_containers.append(container)

        record = {"extra": {}, "title": title}
        description = container_text.replace(title, "", 1).strip(" .:-") or None
        if description:
            record["description"] = description
        _backfill_dates_and_title(record)

        hrefs = [urljoin(page_url, a.get("href")) for a in container.xpath(".//a[@href]")]
        document_links, other_links = _split_links(hrefs)
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
        records = _extract_repeater_records(tree, page_url)
    if not records:
        records = _extract_card_records(tree, page_url)

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
                logger.warning(
                    "%s: no tender table with recognized columns found - falling back to a "
                    "single heading-based record. If this bank has a real multi-row listing, "
                    "tune _COLUMN_HINTS (or add a per-bank override) for its table layout.",
                    page_url,
                )

    for record in records:
        record["source_url"] = page_url
        record["extracted_at"] = utc_timestamp()
        record["classification"] = "pending"
        record["matched_tags"] = []
        record["reason"] = None

    return records
