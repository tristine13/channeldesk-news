"""The Channel Desk: public student news site.

Read-only for students. No login, no register, no staff links. It shares the database and
the uploads folder with the staff app (../app.py) and only ever shows works whose status is
'approved' (the Adviser's final sign-off).

Run:   flask --app app run --port 5001
"""
import os
import re
import secrets
from datetime import datetime
from html import escape

from dotenv import load_dotenv
from flask import (Flask, abort, jsonify, render_template, request,
                   send_from_directory, session)
from markupsafe import Markup

HERE = os.path.dirname(os.path.abspath(__file__))


def first_existing(paths):
    return next((p for p in paths if p and os.path.exists(p)), None)


# Reuse the staff app's settings (DB login) so nothing is copied or duplicated.
# Works whether this folder sits inside the staff project or beside it in htdocs.
load_dotenv(first_existing([os.path.join(HERE, ".env"),
                            os.path.join(HERE, "..", ".env"),
                            os.path.join(HERE, "..", "channeldesk", ".env")]))

from db import close_db, execute, query  # noqa: E402

app = Flask(__name__)
app.secret_key = os.getenv("NEWS_SECRET_KEY") or os.getenv("SECRET_KEY", "dev-only-change-me")
app.teardown_appcontext(close_db)

# Where the staff app saves uploaded pictures
UPLOAD_FOLDER = os.path.abspath(os.getenv("UPLOAD_FOLDER") or first_existing([
    os.path.join(HERE, "..", "uploads"),
    os.path.join(HERE, "..", "channeldesk", "uploads")]) or os.path.join(HERE, "uploads"))

REACTIONS = [("heart", "Heart"), ("applaud", "Applaud"),
             ("insightful", "Insightful"), ("fire", "Fire")]
REACTION_KEYS = [k for k, _ in REACTIONS]
TABS = [("all", "Latest"), ("News", "News"), ("Column", "Op/Ed"),
        ("Feature", "Feature"), ("Sports", "Sports")]
TYPE_LABELS = {"News": "News", "Sports": "Sports", "Feature": "Feature", "Column": "Op/Ed",
               "Op/Ed": "Op/Ed"}
# Campus Pulse: edit the question / options here
POLL = {"question": "What should we cover more of this semester?",
        "options": [("events", "Campus events"), ("sports", "Sports"),
                    ("voices", "Student voices"), ("features", "Long-form features")]}

_ready = False


def ensure_tables():
    """Create the small tables this site writes to, the first time they're needed."""
    global _ready
    if _ready:
        return
    execute("CREATE TABLE IF NOT EXISTS post_reactions (post_id INT NOT NULL, kind VARCHAR(20) "
            "NOT NULL, n INT NOT NULL DEFAULT 0, PRIMARY KEY (post_id, kind))")
    execute("CREATE TABLE IF NOT EXISTS post_views (post_id INT PRIMARY KEY, n INT NOT NULL DEFAULT 0)")
    execute("CREATE TABLE IF NOT EXISTS poll_votes (option_key VARCHAR(30) PRIMARY KEY, "
            "n INT NOT NULL DEFAULT 0)")
    _ready = True


SELECT = (
    "SELECT p.id, p.title, p.content, p.type, p.image, p.created_at, "
    "COALESCE(r.name, u.name, u.email) AS author, r.position AS position, "
    "COALESCE(v.n, 0) AS views "
    "FROM posts p LEFT JOIN users u ON u.id = p.user_id "
    "LEFT JOIN registrations r ON r.email = u.email "
    "LEFT JOIN post_views v ON v.post_id = p.id "
    "WHERE p.status = 'approved' "
)


# ---------------------------------------------------------------- helpers
@app.context_processor
def inject_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return dict(csrf_token=session["csrf"])


@app.before_request
def check_csrf():
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf_token"):
            abort(400, "Invalid CSRF token")


@app.template_filter("ago")
def ago_filter(dt):
    secs = max(0, int((datetime.now() - dt).total_seconds()))
    if secs < 60:
        return "just now"
    for size, name in ((86400 * 7, None), (86400, "d"), (3600, "h"), (60, "m")):
        if secs >= size:
            return dt.strftime("%b %d, %Y") if name is None else f"{secs // size}{name} ago"
    return "just now"


@app.template_filter("excerpt")
def excerpt_filter(text, n=180):
    flat = " ".join((text or "").split())
    return flat if len(flat) <= n else flat[:n].rsplit(" ", 1)[0] + "…"


@app.template_filter("paragraphs")
def paragraphs_filter(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text or "") if p.strip()]
    return Markup("".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in parts))


def images_for(post):
    imgs = [r["image"] for r in query(
        "SELECT image FROM post_images WHERE post_id = %s ORDER BY id", (post["id"],))]
    if post.get("image"):  # legacy single-image column on posts
        imgs.insert(0, post["image"])
    return imgs


def cards(rows):
    """Attach pictures, reaction counts, read time and the visitor's own reaction."""
    mine = session.get("reacted", {})
    ids = [r["id"] for r in rows]
    counts = {}
    if ids:
        marks = ",".join(["%s"] * len(ids))
        for c in query(f"SELECT post_id, kind, n FROM post_reactions WHERE post_id IN ({marks})", ids):
            counts.setdefault(c["post_id"], {})[c["kind"]] = c["n"]
    for r in rows:
        imgs = images_for(r)
        r["cover"] = imgs[0] if imgs else None
        r["images"] = imgs
        r["label"] = TYPE_LABELS.get(r["type"], r["type"])
        r["minutes"] = max(1, round(len((r["content"] or "").split()) / 200))
        r["reactions"] = {k: counts.get(r["id"], {}).get(k, 0) for k in REACTION_KEYS}
        r["total_reactions"] = sum(r["reactions"].values())
        r["my_reaction"] = mine.get(str(r["id"]))
    return rows


def poll_state():
    votes = {r["option_key"]: r["n"] for r in query("SELECT option_key, n FROM poll_votes")}
    opts = [{"key": k, "label": lbl, "n": votes.get(k, 0)} for k, lbl in POLL["options"]]
    total = sum(o["n"] for o in opts)
    for o in opts:
        o["pct"] = round(100 * o["n"] / total) if total else 0
    return {"question": POLL["question"], "options": opts, "total": total,
            "voted": session.get("poll_vote")}


# ------------------------------------------------------------------ pages
@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="We couldn't find that story."), 404


@app.route("/")
@app.route("/news")
def reader_feed():
    ensure_tables()
    rows = cards(query(SELECT + "ORDER BY p.created_at DESC"))
    top = sorted(rows, key=lambda p: (p["views"], p["total_reactions"]), reverse=True)[:5]
    return render_template("reader_feed.html", posts=rows, most_read=top, poll=poll_state(),
                           tabs=TABS, reactions=REACTIONS)


@app.route("/news/<int:post_id>")
def reader_article(post_id):
    ensure_tables()
    row = query(SELECT + "AND p.id = %s", (post_id,), one=True)
    if not row:
        abort(404)
    seen = session.setdefault("seen", [])
    if post_id not in seen:                      # one view per visitor session
        execute("INSERT INTO post_views (post_id, n) VALUES (%s, 1) "
                "ON DUPLICATE KEY UPDATE n = n + 1", (post_id,))
        seen.append(post_id)
        session["seen"] = seen[-200:]
        row["views"] += 1
    post = cards([row])[0]
    more = cards(query(SELECT + "AND p.id <> %s ORDER BY p.created_at DESC LIMIT 3", (post_id,)))
    return render_template("reader_article.html", post=post, more=more, reactions=REACTIONS)


@app.route("/media/<path:filename>")
def reader_media(filename):
    """Pictures of approved works only."""
    ok = query("SELECT p.id FROM posts p LEFT JOIN post_images i ON i.post_id = p.id "
               "WHERE p.status = 'approved' AND (i.image = %s OR p.image = %s) LIMIT 1",
               (filename, filename), one=True)
    if not ok:
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/news/<int:post_id>/react", methods=["POST"])
def reader_react(post_id):
    ensure_tables()
    kind = request.form.get("kind", "")
    if kind not in REACTION_KEYS or not query(
            "SELECT id FROM posts WHERE id=%s AND status='approved'", (post_id,), one=True):
        abort(400)
    mine = dict(session.get("reacted", {}))
    prev = mine.get(str(post_id))
    if prev in REACTION_KEYS:                    # one reaction per visitor: change or remove
        execute("UPDATE post_reactions SET n = GREATEST(n - 1, 0) WHERE post_id=%s AND kind=%s",
                (post_id, prev))
    if prev == kind:
        mine.pop(str(post_id), None)
    else:
        execute("INSERT INTO post_reactions (post_id, kind, n) VALUES (%s,%s,1) "
                "ON DUPLICATE KEY UPDATE n = n + 1", (post_id, kind))
        mine[str(post_id)] = kind
    session["reacted"] = mine
    counts = {k: 0 for k in REACTION_KEYS}
    for c in query("SELECT kind, n FROM post_reactions WHERE post_id=%s", (post_id,)):
        counts[c["kind"]] = c["n"]
    return jsonify(counts=counts, mine=mine.get(str(post_id)), total=sum(counts.values()))


@app.route("/news/poll/vote", methods=["POST"])
def reader_vote():
    ensure_tables()
    key = request.form.get("option", "")
    if key not in dict(POLL["options"]):
        abort(400)
    if not session.get("poll_vote"):             # one vote per visitor session
        execute("INSERT INTO poll_votes (option_key, n) VALUES (%s,1) "
                "ON DUPLICATE KEY UPDATE n = n + 1", (key,))
        session["poll_vote"] = key
    return jsonify(poll_state())


if __name__ == "__main__":
    app.run(debug=True, port=5001)
