"""Small client for the OpenAlex API (https://openalex.org).

It builds the request, calls OpenAlex, keeps recent answers in a cache,
and turns each work into a simple dictionary the web page can show.
"""
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