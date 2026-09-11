"""Keyword/alias-based entity matching, shared by the spider (frontier
priority/pruning, scored against raw extracted text) and EntityRelevancePipeline
(storage gate, scored against the fully cleaned_content)."""

import re


def _compile_patterns(terms):
    return [(term, re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)) for term in terms if term.strip()]


class EntityQuery:
    def __init__(self, name, aliases=None, context=None):
        self.name = name
        self.aliases = aliases or []
        self.context = context or []
        self._name_patterns = _compile_patterns([name] + list(self.aliases))
        self._context_patterns = _compile_patterns(self.context)

    def score(self, text):
        """Returns (score, is_relevant, matched_terms). A page is relevant if
        it mentions the entity's name/an alias, AND - when context terms were
        given - at least one context term too (this is what disambiguates a
        common name from an unrelated same-named entity)."""
        if not text:
            return 0, False, {"name": [], "context": []}

        name_hits = {term: len(pattern.findall(text)) for term, pattern in self._name_patterns}
        name_hits = {term: count for term, count in name_hits.items() if count}

        context_hits = {term: len(pattern.findall(text)) for term, pattern in self._context_patterns}
        context_hits = {term: count for term, count in context_hits.items() if count}

        is_relevant = bool(name_hits) and (bool(context_hits) or not self._context_patterns)
        score = sum(name_hits.values()) * 2 + sum(context_hits.values())
        matched = {"name": sorted(name_hits), "context": sorted(context_hits)}
        return score, is_relevant, matched
