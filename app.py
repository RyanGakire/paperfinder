"""PaperFinder: find research papers to read for free.

A small Flask app. The browser talks only to this server, and this server talks to the OpenAlex API, 
so the API never reaches the browser.
"""
import datetime
import os
import socket

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

from openalex import SORTS, TYPES, OpenAlexClient, OpenAlexError

load_dotenv()

app = Flask(__name__, static_folder="static")
client = OpenAlexClient(
    api_key=os.getenv("OPENALEX_API_KEY", "").strip(),
    cache_seconds=int(os.getenv("CACHE_SECONDS", "600")),
)
SERVER_NAME = socket.gethostname()


MIN_YEAR = 1900
MAX_PAGE = 500 # 10,000 results / 20 per page


class BadInput(Exception):
    """Raised when the user's input is invalid."""


def read_year(name):
    value = request.args.get(name, "").strip()
    if not value:
        return None
    if not value.isdigit():
        raise BadInput("Years must be numbers, like 2015.")
    year = int(value)
    this_year = datetime.date.today().year
    if year < MIN_YEAR or year > this_year:
        raise BadInput(
            "Years must be between {} and {}.".format(MIN_YEAR, this_year)
        )
    return year


def read_search_settings():
    query = " ".join(request.args.get("q", "").split())
    if len(query) < 2:
        raise BadInput("Type at least 2 characters to search.")
    if len(query) > 200:
        raise BadInput("Keep your search under 200 characters.")

    sort = request.args.get("sort", "relevance")
    if sort not in SORTS:
        raise BadInput("Pick a sort option from the list.")

    work_type = request.args.get("type", "any")
    if work_type not in TYPES:
        raise BadInput("Pick a type from the list.")

    year_from = read_year("from")
    year_to = read_year("to")
    if year_from and year_to and year_from > year_to:
        raise BadInput("The 'from' year must come before the 'to' year.")

    page_text = request.args.get("page", "1")
    if not page_text.isdigit() or not 1 <= int(page_text) <= MAX_PAGE:
        raise BadInput("Page must be between 1 and {}.".format(MAX_PAGE))

    return {
        "query": query,
        "free_only": request.args.get("free", "1") != "0",
        "year_from": year_from,
        "year_to": year_to,
        "work_type": work_type,
        "sort": sort,
        "page": int(page_text),
    }


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/search")
def search():
    try:
        settings = read_search_settings()
    except BadInput as error:
        return jsonify(error=str(error)), 400

    try:
        result = client.search(**settings)
    except OpenAlexError as error:
        return jsonify(error=error.message, served_by=SERVER_NAME), \
            error.status

    result["query"] = settings["query"]
    result["served_by"] = SERVER_NAME
    return jsonify(result)


@app.route("/api/health")
def health():
    return jsonify(status="ok", served_by=SERVER_NAME, api_key_set=bool(client.api_key))


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(error="That page doesn't exist."), 404
    return send_from_directory(app.static_folder, "index.html"), 404


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    )
    return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1")