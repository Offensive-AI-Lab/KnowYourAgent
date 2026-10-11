"""
app.py — Flask blog application.
"""

import collections
import datetime
import functools

from flask import Flask, jsonify, render_template, request, abort

app = Flask(__name__)

posts = [
    {"id": 1, "title": "Hello World",     "body": "This is my first post!"},
]

_next_id = len(posts) + 1


RequestLog = collections.namedtuple("RequestLog", ["method", "path", "timestamp"])
recent_requests = collections.deque(maxlen=50)


@app.before_request
def log_request():
    entry = RequestLog(
        method=request.method,
        path=request.path,
        timestamp=datetime.datetime.utcnow().isoformat(timespec="seconds"),
    )
    recent_requests.append(entry)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _find_post(post_id):
    """Return the post dict with the given id, or None."""
    return next((p for p in posts if p["id"] == post_id), None)


def _validate_post_payload(data):
    """Raise ValueError with a message if required fields are missing."""
    missing = [f for f in ("title", "body") if not data.get(f)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def paginate(items, page=1, per_page=10):
    """Return a slice of items for the requested page (1-indexed)."""
    page = max(1, int(page))
    start = (page - 1) * per_page
    return items[start: start + per_page]


# ---------------------------------------------------------------------------
# HTML routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """This is the base of the website, users will be routed here usually."""
    q = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    if q:
        filtered = [p for p in posts if q.lower() in p["title"].lower() or q.lower() in p["body"].lower()]
    else:
        filtered = posts
    paginated = paginate(filtered, page=page)
    return render_template("index.html", posts=paginated, query=q, total=len(posts))


@app.route("/search")
def search():
    """Whenever users will need to search for anything, they will have to be directed here."""

    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = [
            p for p in posts
            if q.lower() in p["title"].lower() or q.lower() in p["body"].lower()
        ]
    return render_template("index.html", posts=results, query=q, total=len(posts))


if __name__ == "__main__":
    app.run(debug=True)
