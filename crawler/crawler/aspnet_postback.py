"""Follows ASP.NET WebForms __doPostBack pagination (confirmed live on PNB's
own Tender.aspx: page 2+ has no real href, only
javascript:__doPostBack('ctl00$...$rptPager$ctl02$lnkPage','')) as a plain
Scrapy FormRequest instead of needing a headless browser - the same
FormRequest.from_response technique crawler.spiders.crawler already uses for
its form_login auth flow. Works because PNB's pager does a full-page
postback (no ScriptManager/UpdatePanel wrapping the grid was found in its
markup - confirmed against the live page), so the response is a normal full
HTML page carrying its own fresh __VIEWSTATE/__EVENTVALIDATION, not an MS
AJAX partial-postback payload. A site that DOES wrap its grid in an
UpdatePanel would need different handling - not implemented here since no
bank site seen so far needs it.
"""
import re

import scrapy

# text of the pager control that means "go to the next page" - matched
# case-insensitively against the link's own visible text, not any bank-
# specific id/class, so this isn't tied to PNB's particular control naming
_NEXT_LINK_TEXT = {"next", "next »", "»", ">", ">>"}
_POSTBACK_HREF_RE = re.compile(r"__doPostBack\(\s*'([^']*)'\s*,\s*'([^']*)'\s*\)")


def find_next_page_postback(response):
    """Return the __EVENTTARGET string for this page's "Next" pager link, or
    None if there isn't one - either this page isn't paginated this way at
    all, or (once the __doPostBack href disappears/goes disabled, as PNB's
    own markup does on the last page) there's no next page left."""
    for link in response.css("a"):
        text = "".join(link.css("*::text").getall()).strip().lower()
        if text not in _NEXT_LINK_TEXT:
            continue
        href = link.attrib.get("href", "")
        match = _POSTBACK_HREF_RE.search(href)
        if match:
            return match.group(1)
    return None


def build_next_page_request(response, event_target, callback, meta):
    """Replicate the __doPostBack('<event_target>', '') click as a real
    FormRequest. FormRequest.from_response carries over every existing
    hidden field (__VIEWSTATE, __EVENTVALIDATION, __VIEWSTATEGENERATOR, ...)
    from the current response automatically - only __EVENTTARGET needs
    overriding, exactly as a browser would set it before submitting."""
    return scrapy.FormRequest.from_response(
        response,
        formdata={"__EVENTTARGET": event_target, "__EVENTARGUMENT": ""},
        callback=callback,
        meta=meta,
        dont_filter=True,
    )
