"""Small client for the OpenAlex API (https://openalex.org).

It builds the request, calls OpenAlex, keeps recent answers in a cache,
and turns each work into a simple dictionary the web page can show.
"""
import time
import requests

OPENALEX_URL = "https://api.openalex.org/works"
PER_PAGE = 20
TIMEOUT_SECONDS = 10

# What the user picks / What OpenAlex expects
SORTS = {
    "relevance": "relevance_score:desc",
    "citations": "cited_by_count:desc",
    "newest": "publication_date:desc",
}
TYPES = {
    "any": None,
    "article": "article",
    "review": "review",
    "book": "book|book-chapter",
    "preprint": "preprint",
    "dissertation": "dissertation",
}

# Only ask OpenAlex for the fields we actually show
SELECT_FIELDS = ",".join([
    "id", 
    "doi", 
    "display_name", 
    "publication_year", 
    "type", 
    "cited_by_count", 
    "authorships", 
    "primary_location", 
    "best_oa_location", 
    "open_access", 
    "primary_topic", 
    "abstract_inverted_index",
])
MAX_AUTHORS = 4

def build_params(query, free_only, year_from, year_to, work_type, sort, page, api_key=""):
    """Turn the user's choices into OpenAlex query parameters."""
    filters = []
    if free_only:
        filters.append("is_oa:true")
    if year_from and year_to:
        filters.append("publication_year:{}-{}".format(year_from, year_to))
    elif year_from:
        filters.append("publication_year:>{}".format(year_from - 1))
    elif year_to:
        filters.append("publication_year:<{}".format(year_to + 1))
    if TYPES.get(work_type):
        filters.append("type:{}".format(TYPES[work_type]))

    params = {
        "search": query,
        "sort": SORTS[sort],
        "per_page": PER_PAGE,
        "page": page,
        "select": SELECT_FIELDS,
    }
    if filters:
        params["filter"] = ",".join(filters)
    if api_key:
        params["api_key"] = api_key
    return params


def rebuild_abstract(inverted_index):
    """OpenAlex stores abstracts as {word: [positions]}. Put them in order."""
    if not inverted_index:
        return None
    words = {}
    for word, positions in inverted_index.items():
        for position in positions:
            words[position] = word
    return " ".join(words[i] for i in sorted(words))


def simplify_work(work):
    """Keep only what the page needs, with safe defaults for missing data."""
    authorships = work.get("authorships") or []
    names = []
    for authorship in authorships:
        author = authorship.get("author") or {}
        if author.get("display_name"):
            names.append(author["display_name"])

    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    best_oa = work.get("best_oa_location") or {}
    open_access  = work.get("open_access") or {}
    topic = work.get("primary_topic") or {}

    is_free = bool(open_access.get("is_oa"))
    free_url = None
    if is_free:
        free_url = (best_oa.get("pdf_url") or best_oa.get("landing_page_url") or open_access.get("oa_url"))

    link = work.get("doi") or primary.get("landing_page_url") or work.get("id")

    return {
        "id": work.get("id"),
        "title": work.get("display_name") or "Untitled",
        "year": work.get("publication_year"),
        "type": work.get("type"),
        "citations": work.get("cited_by_count") or 0,
        "authors": names[:MAX_AUTHORS],
        "more_authors": max(len(names) - MAX_AUTHORS, 0),
        "venue": source.get("display_name"),
        "topic": topic.get("display_name"),
        "is_free": is_free,
        "free_url": free_url,
        "free_is_pdf": bool(is_free and best_oa.get("pdf_url")),
        "link": link,
        "abstract": rebuild_abstract(work.get("abstract_inverted_index")),
    }


class OpenAlexError(Exception):
    """Raised when OpenAlex can't give us a usable answer."""


    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


class TTLCache:
    """Remembers answers for a while so repeated searches are instant."""


    def __init__(self, seconds=600, max_items=200):
        self.seconds = seconds
        self.max_items = max_items
        self._items = {}


    def get(self, key):
        item = self._items.get(key)
        if item is None:
            return None
        saved_at, value = item
        if time.time() - saved_at > self.seconds:
            del self._items[key]
            return None
        return value

    
    def set(self, key, value):
        if len(self._items) >= self.max_items:
            oldest = min(self._items, key=lambda k: self._items[k][0])
            del self._items[oldest]
        self._items[key] = (time.time(), value)


    def clear(self):
        self._items.clear()


class OpenAlexClient:
    """Calls OpenAlex and caches the answers."""


    def __init__(self, api_key="", cache_seconds=600):
        self.api_key = api_key
        self.cache = TTLCache(seconds=cache_seconds)


    def search(self, query, free_only=False, year_from=None, year_to=None, work_type="any", sort="relevance", page=1):
        params = build_params(query, free_only, year_from, year_to, work_type, sort, page, self.api_key)
        cache_key = tuple(sorted(
            (k, str(v)) for k, v in params.items() if k != "api_key"))
        cached = self.cache.get(cache_key)
        if cached is not None:
            return dict(cached, cached=True)

        data = self._fetch(params)
        meta = data.get("meta") or {}
        total = meta.get("count") or 0
        result = {
            "total": total,
            "page": page,
            "per_page": PER_PAGE,
            # OpenAlex only lets you page through the first 10,000 results
            "pages": max(1, -(-min(total, 10000) // PER_PAGE)),
            "results": [simplify_work(work) for work in data.get("results") or []],
        }
        self.cache.set(cache_key, result)
        return dict(result, cached=False)

    
    def _fetch(self, params):
        try:
            response = requests.get(
                OPENALEX_URL, params=params, timeout=TIMEOUT_SECONDS,
                headers={"User-Agent": "PaperFinder/1.0 (student project)"}
            )
        except requests.Timeout:
            raise OpenAlexError(
                "OpenAlex took too long to respond. Try again in a moment.", 504
            )
        except requests.RequestException:
            raise OpenAlexError(
                "Couldn't reach OpenAlex. Try again in a few minutes.", 502
            )

        if response.status_code == 429:
            raise OpenAlexError(
                "Too many searches right now. Wait a minute, then try again.", 503
            )
        if response.status_code == 403:
            raise OpenAlexError(
                "OpenAlex refused the API key. Check OPENALEX_API_KEY in .env (a new key only works after you click the email link).", 502
            )
        if response.status_code != 200:
            raise OpenAlexError(
                "OpenAlex returned an error (status {}). Try a different search.".format(response.status_code), 502
            )

        try:
            return response.json()
        except ValueError:
            raise OpenAlexError(
                "OpenAlex sent an answer we couldn't read. Try again.", 502
            )