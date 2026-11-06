"""Merge duplicate companies across sources by own website domain and by normalised name."""

import re
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable

from pipeline import config
from pipeline.models import Company, Fact, SourceRef, Status
from pipeline.utils.urls import company_id, domain_of, is_platform_domain

_TRANSLITERATION = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_SCALAR_FIELDS = ("name", "phone", "email_general", "street", "postcode", "city")
_FACT_FIELDS = tuple(name for name, f in Company.model_fields.items() if f.annotation is Fact)


def merge_companies(companies: list[Company]) -> list[Company]:
    """Pure: returns new merged records sorted by normalised name, then id."""
    groups = _group_indices(companies)
    merged = [_merge_group([companies[i] for i in group]) for group in groups]
    return sorted(merged, key=lambda c: (normalize_company_name(c.name), c.id))


def normalize_company_name(name: str) -> str:
    text = " ".join(name.lower().translate(_TRANSLITERATION).split())
    text = _strip_legal_forms(text)
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(text.split())


def _suffix_patterns() -> list[re.Pattern[str]]:
    transliterated = (s.lower().translate(_TRANSLITERATION) for s in config.LEGAL_FORM_SUFFIXES)
    suffixes = sorted(transliterated, key=len, reverse=True)
    return [re.compile(_suffix_regex(s)) for s in suffixes]


def _suffix_regex(suffix: str) -> str:
    # Spacing inside a legal form varies ("Co.KG", "GmbH&Co") and a final period is optional.
    body = r"\s*".join(re.escape(token) for token in suffix.rstrip(".").split())
    # A separator (space or comma) before the suffix keeps it a whole word: "Zug" is not "ug".
    return rf"[\s,]+{body}\.?$"


_SUFFIX_PATTERNS = _suffix_patterns()
_GENERIC_NAMES = frozenset(
    " ".join(n.lower().translate(_TRANSLITERATION).split()) for n in config.GENERIC_COMPANY_NAMES
)


def _strip_legal_forms(text: str) -> str:
    while True:
        for pattern in _SUFFIX_PATTERNS:
            if match := pattern.search(text):
                text = text[: match.start()].rstrip()
                break
        else:
            return text


def _own_domain(website: str | None) -> str | None:
    domain = domain_of(website)
    return domain if domain and not is_platform_domain(domain) else None


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


class _Groups:
    """Union-find over record indices that refuses merges which would join different firms."""

    def __init__(self, companies: list[Company]) -> None:
        self._parent = list(range(len(companies)))
        self._domains = [_as_set(_own_domain(c.website)) for c in companies]
        self._postcodes = [_as_set(_clean(c.postcode)) for c in companies]

    def find(self, i: int) -> int:
        while self._parent[i] != i:
            self._parent[i] = self._parent[self._parent[i]]
            i = self._parent[i]
        return i

    def compatible(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if _domains_conflict(self._domains[ra], self._domains[rb]):
            return False
        return not _postcodes_conflict(self._postcodes[ra], self._postcodes[rb])

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb or _domains_conflict(self._domains[ra], self._domains[rb]):
            return
        keep, drop = min(ra, rb), max(ra, rb)
        self._parent[drop] = keep
        self._domains[keep] |= self._domains[drop]
        self._postcodes[keep] |= self._postcodes[drop]

    def groups(self) -> list[list[int]]:
        by_root: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self._parent)):
            by_root[self.find(i)].append(i)
        return list(by_root.values())


def _as_set(value: str | None) -> set[str]:
    return {value} if value else set()


def _domains_conflict(a: set[str], b: set[str]) -> bool:
    return bool(a) and bool(b) and a != b


def _postcodes_conflict(a: set[str], b: set[str]) -> bool:
    return bool(a) and bool(b) and a.isdisjoint(b)


def _group_indices(companies: list[Company]) -> list[list[int]]:
    groups = _Groups(companies)
    for indices in _buckets(companies, lambda c: _own_domain(c.website)).values():
        for i in indices[1:]:
            groups.union(indices[0], i)
    # Name edges are all decided on the domain-only grouping before any is applied,
    # so the input order can never decide which firm a record joins.
    buckets = _buckets(companies, _name_key).values()
    edges = [edge for indices in buckets for edge in _name_edges(companies, indices, groups)]
    for i, j in edges:
        groups.union(i, j)
    return groups.groups()


def _name_edges(
    companies: list[Company], indices: list[int], groups: _Groups
) -> list[tuple[int, int]]:
    """Same-name pairs to join, leaving out records that match more than one distinct firm."""
    neighbours = {
        i: [j for j in indices if j != i and _postcodes_compatible(companies[i], companies[j])]
        for i in indices
    }
    clear = {i for i in indices if not _is_ambiguous(i, neighbours[i], groups)}
    return [
        (i, j)
        for i in sorted(clear)
        for j in neighbours[i]
        if j > i and j in clear and groups.compatible(i, j)
    ]


def _is_ambiguous(i: int, neighbours: list[int], groups: _Groups) -> bool:
    candidates = sorted(
        {groups.find(j) for j in neighbours if groups.compatible(i, j)} - {groups.find(i)}
    )
    return any(
        not groups.compatible(a, b)
        for pos, a in enumerate(candidates)
        for b in candidates[pos + 1 :]
    )


def _buckets(
    companies: list[Company], key: Callable[[Company], str | None]
) -> dict[str, list[int]]:
    buckets: dict[str, list[int]] = defaultdict(list)
    for i, company in enumerate(companies):
        if value := key(company):
            buckets[value].append(i)
    return buckets


def _name_key(company: Company) -> str | None:
    name = normalize_company_name(company.name)
    return name if name and name not in _GENERIC_NAMES else None


def _postcodes_compatible(a: Company, b: Company) -> bool:
    pa, pb = _clean(a.postcode), _clean(b.postcode)
    return pa is None or pb is None or pa == pb


def _merge_group(records: list[Company]) -> Company:
    ordered = sorted(records, key=_source_rank)  # stable sort: ties keep input order
    sources = _unique((s for r in ordered for s in r.sources), lambda s: (s.source, s.source_id))
    contacts = _unique((c for r in ordered for c in r.contacts), lambda c: (c.name, c.email))
    website = _pick_website(ordered)
    scalars = {f: _first_filled(getattr(r, f) for r in ordered) for f in _SCALAR_FIELDS}
    scalars["name"] = scalars["name"] or ordered[0].name
    return Company(
        id=_merged_id(website, sources, ordered[0]),
        website=website,
        sources=[s.model_copy(deep=True) for s in sources],
        contacts=[c.model_copy(deep=True) for c in contacts],
        errors=_unique((e for r in ordered for e in r.errors), lambda e: e),
        **scalars,
        **{f: _pick_fact([getattr(r, f) for r in ordered]) for f in _FACT_FIELDS},
    )


def _source_rank(company: Company) -> int:
    source = company.sources[0].source if company.sources else None
    if source in config.SOURCE_PRIORITY:
        return config.SOURCE_PRIORITY.index(source)
    return len(config.SOURCE_PRIORITY)


def _unique[T](items: Iterable[T], key: Callable[[T], Hashable]) -> list[T]:
    seen: set[Hashable] = set()
    result: list[T] = []
    for item in items:
        if (k := key(item)) not in seen:
            seen.add(k)
            result.append(item)
    return result


def _first_filled(values: Iterable[str | None]) -> str | None:
    return next((v for v in values if v and v.strip()), None)


def _pick_website(ordered: list[Company]) -> str | None:
    own = _first_filled(r.website for r in ordered if _own_domain(r.website))
    return own or _first_filled(r.website for r in ordered)


def _pick_fact(facts: list[Fact]) -> Fact:
    known = next((f for f in facts if f.status != Status.UNKNOWN), facts[0])
    return known.model_copy(deep=True)


def _merged_id(website: str | None, sources: list[SourceRef], primary: Company) -> str:
    if sources:
        return company_id(website, sources[0].source, sources[0].source_id)
    return _own_domain(website) or primary.id
