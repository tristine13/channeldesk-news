"""The Channel Desk: public student news site.

Read-only for students. No login, no register, no staff links. It shares the database and
the uploads folder with the staff app (../app.py) and only ever shows works whose status is
'approved' (the Adviser's final sign-off).

Run:   flask --app app run --port 5001
"""
import json
import os
import re
import secrets
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import base64
import binascii

from flask import (Flask, Response, abort, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
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
import richtext  # noqa: E402

app = Flask(__name__)
app.secret_key = os.getenv("NEWS_SECRET_KEY") or os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_NAME"] = "channeldesk_news"   # separate from the staff app's cookie (same host, other port)
app.teardown_appcontext(close_db)

# Where the staff app saves uploaded pictures
UPLOAD_FOLDER = os.path.abspath(os.getenv("UPLOAD_FOLDER") or first_existing([
    os.path.join(HERE, "..", "uploads"),
    os.path.join(HERE, "..", "channeldesk", "uploads")]) or os.path.join(HERE, "uploads"))

# The publication's logo: use this site's own static/images, else the staff app's copy
# (also accepts the name "channellogo.png.png", which Windows creates when file extensions are hidden)
LOGO_DIR = first_existing([os.path.join(base, "static", "images", name)
                           for base in (HERE, os.path.join(HERE, "..", "channeldesk"), os.path.join(HERE, ".."))
                           for name in ("channellogo.png", "channellogo.png.png", "channellogo.jpg")])

CAMPUS_PHOTO = first_existing([os.path.join(HERE, "static", "images", "fbc.jpg"),
                               os.path.join(HERE, "..", "channeldesk", "static", "images", "fbc.jpg"),
                               os.path.join(HERE, "..", "static", "images", "fbc.jpg")])

# The Channel's Facebook page. (An old FACEBOOK_URL line in .env is deliberately ignored: a placeholder
# like "<your-page>" there is what produced the broken link.)
FACEBOOK_URL = "https://web.facebook.com/thechannelFBC"

TZ = ZoneInfo(os.getenv("APP_TZ", "Asia/Manila"))


REACTIONS = [("heart", "Heart")]     # one reaction only: a maroon heart
REACTION_KEYS = [k for k, _ in REACTIONS]
# (url slug, label, post types that belong to it). Old "Column" / "Op/Ed" posts count as Opinion.
SECTIONS = [("news", "News", ["News"]),
            ("editorial", "Editorial", ["Editorial"]),
            ("opinion", "Opinion", ["Opinion", "Column", "Op/Ed"]),
            ("feature", "Feature", ["Feature"]),
            ("literary", "Literary", ["Literary"]),
            ("sci-tech", "Sci-Tech", ["Sci-Tech"]),
            ("sports", "Sports", ["Sports"]),
            ("lokal", "Lokal", ["Lokal"])]
SECTION_OF = {t: slug for slug, _, types in SECTIONS for t in types}
SECTION_LABEL = {slug: label for slug, label, _ in SECTIONS}
TYPE_LABELS = {t: label for _, label, types in SECTIONS for t in types}
# Campus Pulse polls are created and closed by the Adviser / Editor-in-Chief in the staff app (Polls page).

# Landing page "Watch Now": the first video is the large one, the next two sit beside it.
# Add entries like {"title": "...", "url": "https://www.youtube.com/watch?v=..."}. YouTube links get
# their thumbnail automatically; for other sites add "thumb": "https://.../picture.jpg".
# Empty slots show a "coming soon" card.
VIDEOS = []

_ready = False


def watch_items():
    """Exactly three cards for the Watch Now section (real videos first, then placeholders)."""
    items = []
    for v in VIDEOS[:3]:
        thumb = v.get("thumb")
        m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{11})", v.get("url", ""))
        if not thumb and m:
            thumb = f"https://img.youtube.com/vi/{m.group(1)}/hqdefault.jpg"
        items.append({"title": v.get("title", ""), "url": v.get("url", "#"), "thumb": thumb})
    while len(items) < 3:
        items.append(None)
    return items


def ensure_tables():
    """Create the small tables this site writes to, the first time they're needed."""
    global _ready
    if _ready:
        return
    try:                                 # the staff app adds this too; whichever starts first does it
        has = query("SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE() "
                    "AND table_name = 'posts' AND column_name = 'approved_at'", one=True)
        if not has["n"]:
            execute("ALTER TABLE posts ADD COLUMN approved_at DATETIME NULL")
        have = {r["cn"].lower() for r in query(
            "SELECT column_name AS cn FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = 'posts' AND column_name IN ('deck', 'image_caption', 'archived_at')")}
        if "archived_at" not in have:
            execute("ALTER TABLE posts ADD COLUMN archived_at DATETIME NULL")
        if "deck" not in have:
            execute("ALTER TABLE posts ADD COLUMN deck VARCHAR(300) NULL")
        if "image_caption" not in have:
            execute("ALTER TABLE posts ADD COLUMN image_caption VARCHAR(300) NULL")
    except Exception as exc:
        print(f"[news] could not add posts columns: {exc}")
    for ddl in (
        "CREATE TABLE IF NOT EXISTS post_reactions (post_id INT NOT NULL, kind VARCHAR(20) NOT NULL, "
        "n INT NOT NULL DEFAULT 0, PRIMARY KEY (post_id, kind))",
        "CREATE TABLE IF NOT EXISTS post_views (post_id INT NOT NULL PRIMARY KEY, n INT NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS poll_votes (option_key VARCHAR(40) NOT NULL PRIMARY KEY, "
        "n INT NOT NULL DEFAULT 0)",
        # Campus Pulse polls (same definitions as the staff app, which creates them as well)
        "CREATE TABLE IF NOT EXISTS polls (id INT AUTO_INCREMENT PRIMARY KEY, question VARCHAR(255) NOT NULL, "
        "options TEXT NOT NULL, starts_at DATETIME NOT NULL, ends_at DATETIME NOT NULL, created_by INT NOT NULL, "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, notified_open TINYINT(1) NOT NULL DEFAULT 0, "
        "notified_close TINYINT(1) NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS poll_vote_counts (poll_id INT NOT NULL, option_idx INT NOT NULL, "
        "n INT NOT NULL DEFAULT 0, PRIMARY KEY (poll_id, option_idx))",
    ):
        execute(ddl)
    _ready = True


SELECT = (
    # created_at here is the APPROVAL time (falls back to the creation time for older works)
    "SELECT p.id, p.user_id, p.title, p.content, p.type, p.image, p.deck, p.image_caption, "
    "COALESCE(p.approved_at, p.created_at) AS created_at, "
    "COALESCE(r.name, u.name, u.email) AS author, r.position AS position, "
    "COALESCE(v.n, 0) AS views "
    "FROM posts p LEFT JOIN users u ON u.id = p.user_id "
    "LEFT JOIN registrations r ON r.email = u.email "
    "LEFT JOIN post_views v ON v.post_id = p.id "
    "WHERE p.status = 'approved' AND p.archived_at IS NULL "      # archived works are hidden from readers
)


# ---------------------------------------------------------------- helpers
@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return dict(csrf_token=session["csrf"], sections=SECTIONS, facebook_url=FACEBOOK_URL)


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
    flat = " ".join(richtext.to_plain(text).split())      # drop the bold / italic markers and any HTML
    return flat if len(flat) <= n else flat[:n].rsplit(" ", 1)[0] + "…"


# staff write **bold** and *italic* with the editor's B / I buttons; shown here as real bold / italic
_BOTH = re.compile(r"\*\*\*(.+?)\*\*\*", re.S)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITAL = re.compile(r"(?<!\*)\*(?!\s|\*)(.+?)(?<![\s*])\*(?!\*)", re.S)


def rich_html(escaped):
    escaped = _BOTH.sub(r"<strong><em>\1</em></strong>", escaped)
    return _ITAL.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", escaped))


@app.template_filter("paragraphs")
def paragraphs_filter(text):
    if richtext.is_rich(text):                    # written in the Word-style editor (already cleaned)
        return Markup(richtext.html_of(text))
    parts = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text or "") if p.strip()]
    return Markup("".join(f"<p>{rich_html(escape(p)).replace(chr(10), '<br>')}</p>" for p in parts))


def images_for(post):
    imgs = [r["image"] for r in query(
        "SELECT image FROM post_images WHERE post_id = %s ORDER BY id", (post["id"],))]
    if post.get("image"):  # legacy single-image column on posts
        imgs.insert(0, post["image"])
    return imgs


_pic_col_ok = True


def big_picture(url, size=512):
    """Google serves profile pictures at 96 px by default (blurry when enlarged): ask for a larger copy."""
    if not url or "googleusercontent.com" not in url:
        return url
    if re.search(r"=s\d+(-[\w-]+)?$", url):
        return re.sub(r"=s\d+(-[\w-]+)?$", f"=s{size}-c", url)
    return url if "=" in url.rsplit("/", 1)[-1] else f"{url}=s{size}-c"


def author_pictures(rows):
    """{user_id: Google profile picture URL}; empty if the staff app hasn't stored pictures yet."""
    global _pic_col_ok
    uids = sorted({r["user_id"] for r in rows if r.get("user_id")})
    if not uids or not _pic_col_ok:
        return {}
    try:
        marks = ",".join(["%s"] * len(uids))
        return {u["id"]: big_picture(u["picture"], 128) for u in query(
            f"SELECT id, picture FROM users WHERE id IN ({marks}) AND picture IS NOT NULL AND picture <> ''", uids)}
    except Exception:
        _pic_col_ok = False                      # no users.picture column yet (restart after the staff app adds it)
        return {}


def cards(rows):
    """Attach pictures, reaction counts, read time and the visitor's own reaction."""
    mine = session.get("reacted", {})
    pics = author_pictures(rows)
    ids = [r["id"] for r in rows]
    counts = {}
    if ids:
        marks = ",".join(["%s"] * len(ids))
        for c in query(f"SELECT post_id, kind, n FROM post_reactions WHERE post_id IN ({marks})", ids):
            counts.setdefault(c["post_id"], {})[c["kind"]] = c["n"]
    for r in rows:
        imgs = images_for(r)
        r["author_pic"] = pics.get(r.get("user_id"))
        r["cover"] = imgs[0] if imgs else None
        r["images"] = imgs
        r["label"] = TYPE_LABELS.get(r["type"], r["type"])
        r["minutes"] = max(1, round(len(richtext.to_plain(r["content"]).split()) / 200))
        r["reactions"] = {k: counts.get(r["id"], {}).get(k, 0) for k in REACTION_KEYS}
        r["total_reactions"] = sum(r["reactions"].values())
        r["my_reaction"] = mine.get(str(r["id"]))
    return rows


def poll_state():
    """The Campus Pulse poll to show: the one open right now, else the most recently closed one.
    status is 'open', 'closed' or 'none' (nothing to show; the box is hidden)."""
    ensure_tables()
    now = datetime.now()
    row = query("SELECT * FROM polls WHERE starts_at <= %s AND ends_at > %s "
                "ORDER BY starts_at DESC LIMIT 1", (now, now), one=True)
    status = "open"
    if not row:
        row = query("SELECT * FROM polls WHERE ends_at <= %s ORDER BY ends_at DESC LIMIT 1", (now,), one=True)
        status = "closed"
    if not row:
        return {"status": "none"}
    labels = json.loads(row["options"])
    votes = {r["option_idx"]: r["n"] for r in query(
        "SELECT option_idx, n FROM poll_vote_counts WHERE poll_id = %s", (row["id"],))}
    opts = [{"key": str(i), "label": lbl, "n": votes.get(i, 0)} for i, lbl in enumerate(labels)]
    total = sum(o["n"] for o in opts)
    for o in opts:
        o["pct"] = round(100 * o["n"] / total) if total else 0
    return {"id": row["id"], "status": status, "question": row["question"], "options": opts,
            "total": total, "voted": session.get("poll_votes", {}).get(str(row["id"])),
            "ends": row["ends_at"].strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")}


# ------------------------------------------------------------------ pages
@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="We couldn't find that story."), 404


@app.route("/")
def landing():
    """Front page: the hero, then the latest works one screen at a time, each tagged by section."""
    ensure_tables()
    rows = cards(query(SELECT + "ORDER BY COALESCE(p.approved_at, p.created_at) DESC"))
    works = rows[:12]
    for p in works:
        p["slug"] = SECTION_OF.get(p["type"], "")
    # side buttons: position of the newest work of each section (None = nothing published there yet)
    pills = [(slug, label, next((i for i, p in enumerate(works) if p["slug"] == slug), None))
             for slug, label, _ in SECTIONS]
    # most read: views first, then reactions (ties keep the newest first)
    trending = sorted(rows, key=lambda p: (p["views"], p["total_reactions"]), reverse=True)[:3]
    for p in trending:
        p["slug"] = SECTION_OF.get(p["type"], "")
    return render_template("landing.html", works=works, pills=pills, total=len(rows), trending=trending)


@app.route("/news")
@app.route("/section/<slug>")
def reader_feed(slug=None):
    """All stories, or one section (News, Opinion, ...)."""
    ensure_tables()
    if slug is not None and slug not in SECTION_LABEL:
        abort(404)
    rows = cards(query(SELECT + "ORDER BY COALESCE(p.approved_at, p.created_at) DESC"))
    top = sorted(rows, key=lambda p: (p["views"], p["total_reactions"]), reverse=True)[:5]
    if slug:
        rows = [p for p in rows if SECTION_OF.get(p["type"]) == slug]
    return render_template("reader_feed.html", posts=rows, most_read=top, poll=poll_state(),
                           reactions=REACTIONS, current=slug or "all",
                           section_label=SECTION_LABEL.get(slug))


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
    more = cards(query(SELECT + "AND p.id <> %s ORDER BY COALESCE(p.approved_at, p.created_at) DESC LIMIT 3", (post_id,)))
    return render_template("reader_article.html", post=post, more=more, reactions=REACTIONS)


# ---- Board page: the staff members of The Channel Desk (verified accounts, never the Admin) ----
MEMBER_RANK = {"adviser": 0, "editor_in_chief": 1, "news_editor": 2, "staff": 3}
MEMBER_TITLE = {"adviser": "Adviser", "editor_in_chief": "Editor-in-Chief", "news_editor": "Editor"}
_photo_col = False          # cache: (table alias, column) of a member picture column, or None


def member_photo_column():
    """Find an optional picture column on registrations / users (photo, avatar, picture, ...)."""
    global _photo_col
    if _photo_col is False:
        _photo_col = None
        try:
            for table, alias in (("registrations", "r"), ("users", "u")):
                row = query("SELECT column_name AS col FROM information_schema.columns "
                            "WHERE table_schema = DATABASE() AND table_name = %s AND column_name IN "
                            "('photo','avatar','picture','profile_image','profile_photo','image') LIMIT 1",
                            (table,), one=True)
                if row:
                    _photo_col = (alias, row["col"])
                    break
        except Exception:
            _photo_col = None
    return _photo_col


def board_members():
    col = member_photo_column()
    photo = f", {col[0]}.`{col[1]}` AS photo" if col else ", NULL AS photo"
    rows = query("SELECT COALESCE(r.name, u.name, u.email) AS name, r.position AS position, "
                 f"u.role AS role{photo} FROM registrations r JOIN users u ON u.email = r.email "
                 "WHERE r.is_verified = 1 AND u.role <> 'admin'")
    for m in rows:
        m["title"] = MEMBER_TITLE.get(m["role"]) or m["position"] or "Staff"
        p = (m.get("photo") or "").strip()
        m["photo_url"] = big_picture(p) if p.startswith(("http://", "https://")) else (
            url_for("member_photo", filename=p) if p else None)
        m["initial"] = (m["name"] or "?")[:1].upper()
    rows.sort(key=lambda m: (MEMBER_RANK.get(m["role"], 9), (m["name"] or "").lower()))
    return rows


@app.route("/board")
def board():
    return render_template("board.html", members=board_members())


# ---- Tabloids / Magazines: the published works grouped by the kind of reading they are ----
TABLOID_SECTIONS = ["news", "sports", "lokal"]                 # quick, punchy reads
MAGAZINE_SECTIONS = ["feature", "opinion", "literary", "sci-tech"]   # long-form, editorial reads


def works_in(slugs):
    rows = cards(query(SELECT + "ORDER BY COALESCE(p.approved_at, p.created_at) DESC"))
    for p in rows:
        p["slug"] = SECTION_OF.get(p["type"], "")
    return [p for p in rows if p["slug"] in slugs]


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/tabloids")
def tabloids():
    ensure_tables()
    return render_template("tabloids.html", works=works_in(TABLOID_SECTIONS),
                           names=[SECTION_LABEL[s] for s in TABLOID_SECTIONS])


@app.route("/magazines")
def magazines():
    ensure_tables()
    return render_template("magazines.html", works=works_in(MAGAZINE_SECTIONS),
                           names=[SECTION_LABEL[s] for s in MAGAZINE_SECTIONS])


@app.route("/board/photo/<path:filename>")
def member_photo(filename):
    """A member's picture, only if it is really attached to a verified member."""
    if not any(m.get("photo") == filename for m in board_members()):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/brand/logo.png")
def brand_logo():
    if not LOGO_DIR:
        abort(404)
    return send_from_directory(os.path.dirname(os.path.abspath(LOGO_DIR)), os.path.basename(LOGO_DIR))


@app.route("/brand/header-logo.png")
def brand_header_logo():
    """Gold eagle on a transparent background, for the dark landing header (stored in header_logo.b64)."""
    try:
        with open(os.path.join(HERE, "header_logo.b64"), "r", encoding="ascii") as f:
            data = base64.b64decode(f.read().strip(), validate=True)
    except (OSError, binascii.Error, ValueError):
        return brand_logo()                      # fall back to the standard logo
    return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.route("/brand/campus.jpg")
def brand_campus():
    """The college photo used behind the landing-page hero."""
    if not CAMPUS_PHOTO:
        abort(404)
    return send_from_directory(os.path.dirname(os.path.abspath(CAMPUS_PHOTO)), "fbc.jpg")


@app.route("/media/<path:filename>")
def reader_media(filename):
    """Pictures of approved works only."""
    ok = query("SELECT p.id FROM posts p LEFT JOIN post_images i ON i.post_id = p.id "
               "WHERE p.status = 'approved' AND p.archived_at IS NULL AND (i.image = %s OR p.image = %s) LIMIT 1",
               (filename, filename), one=True)
    if not ok:
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/news/<int:post_id>/react", methods=["POST"])
def reader_react(post_id):
    ensure_tables()
    kind = request.form.get("kind", "")
    if kind not in REACTION_KEYS or not query(
            "SELECT id FROM posts WHERE id=%s AND status='approved' AND archived_at IS NULL", (post_id,), one=True):
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
    state = poll_state()
    key = request.form.get("option", "")
    if state["status"] != "open" or key not in [o["key"] for o in state["options"]]:
        abort(400)                               # no poll open (or closed meanwhile), or a bad option
    votes = dict(session.get("poll_votes", {}))
    if str(state["id"]) not in votes:            # one vote per visitor session, per poll
        execute("INSERT INTO poll_vote_counts (poll_id, option_idx, n) VALUES (%s,%s,1) "
                "ON DUPLICATE KEY UPDATE n = n + 1", (state["id"], int(key)))
        votes[str(state["id"])] = key
        session["poll_votes"] = votes
    return jsonify(poll_state())


if __name__ == "__main__":
    app.run(debug=True, port=5001)
