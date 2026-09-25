"""Discovers and consumes a Liferay "headless object" REST API
(/o/c/<object-name>) behind a bank's client-side-rendered tender listing.

Confirmed live on Canara Bank's Tenders page, whose raw server HTML has
ZERO tender content at all - not a column-matching problem, a rendering
one. Liferay (a common enterprise CMS on Indian bank/PSU sites) serves the
actual listing through a "Client Extension" JS bundle (Liferay's own naming
convention: .../<keyword>-cx/js/main.<hash>.js) that fetches from a public,
unauthenticated JSON endpoint shaped /o/c/<object-name>?page=N&pageSize=M -
confirmed on Canara as /o/c/tendersmasters, returning descriptionEnglish/
issuedBy/tenderRefNo/tenderDate/lastDate fields mapping directly onto this
project's own tender schema.

/o/c/{objectApiName} is a standard Liferay product convention, not specific
to Canara Bank's own setup - the object's name varies per site (a different
Liferay-based bank would name its own object something else), so this does
a two-step discovery (find a tender-related -cx bundle -> find the /o/c/
path referenced inside it) rather than hardcoding "tendersmasters".
"""
import json
import re
from urllib.parse import urljoin

from crawler.tender import tender_page_score, utc_timestamp

# frontend-js-web/frontend-js-aui-web are Liferay's own portal JS module
# paths, present on every page a Liferay instance serves regardless of
# what's on it - a reliable "this is a Liferay site" signal
_LIFERAY_SIGNAL_RE = re.compile(r"/o/frontend-js-(?:web|aui-web)/")
# the "/js/" segment is sometimes followed by a literal backslash instead of
# a forward slash before the bundle filename (confirmed live on Canara's own
# page - a build-tool artifact, not a typo on our end) - accept either
_CX_BUNDLE_SRC_RE = re.compile(r'<script[^>]+src="([^"]*-cx/js[/\\][^"]+\.js[^"]*)"', re.IGNORECASE)
_HEADLESS_OBJECT_RE = re.compile(r"/o/c/([a-z][a-z0-9_-]*)", re.IGNORECASE)


def looks_like_liferay(html):
    return bool(_LIFERAY_SIGNAL_RE.search(html or ""))


def find_tender_cx_bundle_url(html, page_url):
    """Finds a <script src> for a Liferay Client Extension bundle whose own
    path reads as tender-related (e.g. ".../tender-cx/js/main.<hash>.js") -
    scored the same way a link's relevance is scored elsewhere in this
    module, so it isn't tied to any one bank's exact bundle name. Returns
    None if no such bundle is referenced (e.g. a Liferay site whose
    tenders page is ordinary server-rendered HTML - the common case, this
    is only needed for the client-side-rendered one)."""
    best_url, best_score = None, 0
    for match in _CX_BUNDLE_SRC_RE.finditer(html or ""):
        # browsers normalize a backslash in a URL path to a forward slash;
        # do the same before urljoin so the request we actually send
        # matches what a real browser would fetch
        src = match.group(1).replace("\\", "/")
        score = tender_page_score(src)
        if score > best_score:
            best_url, best_score = urljoin(page_url, src), score
    return best_url


def find_headless_object_path(js_text):
    """Finds a Liferay headless-object API path (/o/c/<name>) referenced
    inside a client extension bundle's source. A bundle commonly references
    more than one object - confirmed live on Canara's own bundle, which
    calls a "tendersmasters" object for the listing itself but also a
    "tenderdocuments" one (presumably per-tender attachments) and a
    "tenderammendments" one elsewhere. The object's NAME isn't a reliable
    signal to pick between them (tender_page_score's word-boundary matching
    doesn't land inside a concatenated compound word like "tendersmasters"
    at all, and even a plain substring check can't distinguish "the
    listing" from "attachments for one tender" - both plausibly contain
    "tender"). What's actually reliable: Liferay's own REST convention
    for a paginated LIST endpoint always takes page/pageSize query params,
    so whichever /o/c/ path is immediately followed by a "page=" query
    build is the listing endpoint, regardless of what it's named."""
    js_text = js_text or ""
    candidates = list(_HEADLESS_OBJECT_RE.finditer(js_text))

    for match in candidates:
        window = js_text[match.end():match.end() + 150]
        if "page=" in window:
            return f"/o/c/{match.group(1)}"

    # fallback for a bundle shaped differently enough that the page=
    # proximity check didn't land on anything - best-effort substring
    # match (not tender_page_score's word-boundary version, which can't
    # match inside a compound identifier) against whichever candidate
    # exists at all
    for match in candidates:
        name = match.group(1).lower()
        if any(kw in name for kw in ("tender", "rfp", "procurement", "nit", "eoi")):
            return f"/o/c/{match.group(1)}"

    return None


def build_listing_url(base_url, object_path, page=1, page_size=50):
    return f"{urljoin(base_url, object_path)}?page={page}&pageSize={page_size}&sort=dateCreated:desc"


# API field name (lowercased) -> canonical tender field. Checked in this
# order per field so a more specific alias never loses to a vaguer one
# that happens to appear earlier in the response object - same reasoning
# as crawler.tender._match_column's longest-hint-wins rule, just against a
# fixed alias list here since JSON field names are exact, not freeform
# header text needing fuzzy matching.
_FIELD_ALIASES = {
    "title": ["title", "name", "subject"],
    "description": ["descriptionenglish", "description", "detail", "details"],
    "office": ["issuedby", "office", "department", "branch"],
    "reference_no": ["tenderrefno", "referenceno", "refno", "tenderid"],
    "published_date": ["tenderdate", "publisheddate", "startdate", "createddate"],
    "closing_date": ["lastdate", "closingdate", "duedate", "enddate"],
}
# fields from a Liferay object entry that are Liferay/API bookkeeping, never
# useful tender content - dropped rather than dumped into "extra" noise
_IGNORED_API_KEYS = {
    "actions", "creator", "taxonomyCategoryBriefs", "keywords", "status",
    "scopeId", "objectEntryFolderId", "objectEntryFolderExternalReferenceCode",
    "externalReferenceCode", "id", "dateCreated", "dateModified", "createdBy",
}


def _map_item_fields(item):
    lower_keys = {k.lower(): k for k in item.keys()}
    record = {"extra": {}}
    used_keys = set()
    for field, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            key = lower_keys.get(alias)
            if key is None:
                continue
            value = item.get(key)
            if isinstance(value, str):
                # source data commonly embeds its own line-wrapping (confirmed
                # live: Canara Bank titles like "Construction of Canara\n\nBank
                # Head Office\n\nAnnex...") - collapse it like every other
                # text field extracted elsewhere in this project already does
                value = re.sub(r"\s+", " ", value).strip()
            if value not in (None, ""):
                record[field] = value
                used_keys.add(key)
            break

    for key, value in item.items():
        if key in used_keys or key in _IGNORED_API_KEYS:
            continue
        if isinstance(value, (dict, list)) or value in (None, ""):
            continue
        record["extra"][key] = value

    return record


def extract_records_from_api_response(response_body, page_url):
    """Parses one page of a Liferay headless-object API JSON response into
    tender records, using the same unfiltered/"classification": "pending"
    contract crawler.tender.extract_tender_records already follows - a
    later, separate step still decides relevance against a user's tags.
    Returns (records, total_count); total_count drives pagination (see the
    spider's _parse_liferay_api_page)."""
    try:
        data = json.loads(response_body)
    except (json.JSONDecodeError, TypeError):
        return [], 0

    records = []
    for item in data.get("items", []) or []:
        record = _map_item_fields(item)
        if not record.get("title") and not record.get("description"):
            continue
        if not record.get("title"):
            record["title"] = record["description"]
        record.setdefault("document_links", [])
        record.setdefault("detail_url", None)
        record["source_url"] = page_url
        record["extracted_at"] = utc_timestamp()
        record["classification"] = "pending"
        record["matched_tags"] = []
        record["reason"] = None
        records.append(record)

    return records, data.get("totalCount", 0)
