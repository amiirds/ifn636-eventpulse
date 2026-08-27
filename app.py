"""EventPulse - a focused Flask event-feedback demonstrator for IFN636."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


# Three tables is all this system needs. Organisers own events, and events own responses.
# "IF NOT EXISTS" lets the app start on an empty machine without a separate setup step.
SCHEMA = """
CREATE TABLE IF NOT EXISTS organisers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organiser_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    location TEXT NOT NULL,
    form_title TEXT NOT NULL DEFAULT 'How was your event experience?',
    question_text TEXT NOT NULL DEFAULT 'How would you rate this event overall?',
    published INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (organiser_id) REFERENCES organisers(id)
);

CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    -- The CHECK is a second line of defence. Even if a bad request slips past the
    -- Python validation, SQLite refuses to store a rating outside 1 to 5.
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id)
);
"""


def utc_now() -> str:
    """Timestamp every row in UTC so the order of responses is never ambiguous."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_local_env(env_path: Path) -> None:
    """Load simple KEY=value pairs for local development without a dependency."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("'\"")


def create_app(test_config=None):
    load_local_env(Path(__file__).with_name(".env"))
    app = Flask(__name__)
    # Secrets come from the environment, never from the source code. The fallback
    # values only exist so the app still runs on a clean checkout.
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("EVENTPULSE_SECRET_KEY", "development-only-change-me"),
        DATABASE=str(Path(app.instance_path) / "eventpulse.sqlite"),
        DEMO_PASSWORD=os.environ.get("EVENTPULSE_DEMO_PASSWORD", "eventpulse-demo"),
        GEOAPIFY_API_KEY=os.environ.get("GEOAPIFY_API_KEY", ""),
    )
    if test_config:
        app.config.update(test_config)

    def get_db():
        # Flask gives each request its own "g" object. Reusing one connection per
        # request is faster than opening a new one for every query.
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            # Row so templates can say event.name instead of event[2]
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = get_db()
        db.executescript(SCHEMA)
        db.commit()

    def seed_demo_organiser():
        """Create the single organiser account.

        There is no sign-up page on purpose. EventPulse serves one organising team,
        so accounts are provisioned rather than self-registered. Attendees never get
        an account at all, because responses are anonymous by design.
        """
        db = get_db()
        exists = db.execute(
            "SELECT id FROM organisers WHERE email = ?", ("organiser@eventpulse.local",)
        ).fetchone()
        if exists is None:
            db.execute(
                "INSERT INTO organisers (email, password_hash) VALUES (?, ?)",
                (
                    "organiser@eventpulse.local",
                    # The plain password is never stored, only a one-way hash of it.
                    generate_password_hash(app.config["DEMO_PASSWORD"]),
                ),
            )
            db.commit()

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()
        seed_demo_organiser()

    def login_required(view):
        """Block every organiser page for visitors who are not signed in.

        Writing this once as a decorator means a new organiser route cannot be left
        unprotected by accident. Forgetting @login_required is the usual way this
        kind of bug happens.
        """
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "organiser_id" not in session:
                flash("Please sign in to access organiser tools.", "error")
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    def organiser_event_or_404(event_id):
        """Load an event, but only if the signed-in organiser owns it.

        The organiser_id filter is the important part. Without it, changing the
        number in the URL would show another organiser's event.
        """
        event = get_db().execute(
            "SELECT * FROM events WHERE id = ? AND organiser_id = ?",
            (event_id, session["organiser_id"]),
        ).fetchone()
        if event is None:
            abort(404)
        return event

    @app.route("/")
    def index():
        # The home page asks the visitor which role they are, matching the Figma
        # "Start" screen. Attendees normally arrive from a link the organiser shares,
        # so the attendee card points at the newest published form as a way in.
        latest_published = get_db().execute(
            "SELECT id FROM events WHERE published = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return render_template("start.html", latest_published=latest_published)

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if "organiser_id" in session:
            return redirect(url_for("events"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            organiser = get_db().execute(
                "SELECT * FROM organisers WHERE email = ?", (email,)
            ).fetchone()
            # One message for both failures. Saying "no such email" would tell an
            # attacker which addresses exist.
            if organiser is None or not check_password_hash(organiser["password_hash"], password):
                flash("Email or password was not recognised.", "error")
            else:
                # Clearing first stops an old session id from being reused after login.
                session.clear()
                session["organiser_id"] = organiser["id"]
                session["organiser_email"] = organiser["email"]
                return redirect(url_for("events"))
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @app.route("/events")
    @login_required
    def events():
        # An empty search box becomes "%%", which LIKE matches against every name.
        # That avoids an if statement and keeps this to a single query.
        search = request.args.get("q", "").strip()
        rows = get_db().execute(
            # LEFT JOIN, not JOIN: an event with zero responses must still be listed.
            # GROUP BY then counts the responses belonging to each event.
            "SELECT e.*, COUNT(r.id) AS response_count "
            "FROM events e LEFT JOIN responses r ON r.event_id = e.id "
            "WHERE e.organiser_id = ? AND e.name LIKE ? "
            "GROUP BY e.id ORDER BY e.created_at DESC",
            (session["organiser_id"], f"%{search}%"),
        ).fetchall()
        return render_template("events.html", events=rows, search=search)

    @app.route("/events/new", methods=("GET", "POST"))
    @login_required
    def create_event():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            event_date = request.form.get("event_date", "")
            location = request.form.get("location", "").strip()
            # Validation happens on the server. A browser can skip the HTML "required"
            # attribute, so the server must never trust the request.
            if not name or not event_date or not location:
                flash("Event name, date, and location are all required.", "error")
            else:
                db = get_db()
                cursor = db.execute(
                    """INSERT INTO events (organiser_id, name, event_date, location, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (session["organiser_id"], name, event_date, location, utc_now()),
                )
                db.commit()
                flash("Event created. Now configure its feedback form.", "success")
                return redirect(url_for("edit_form", event_id=cursor.lastrowid))
        return render_template("event_new.html")

    @app.get("/api/location-suggestions")
    @login_required
    def location_suggestions():
        """Ask Geoapify for venue suggestions on behalf of the browser.

        The browser calls this route, and this route calls Geoapify. That way the
        API key stays on the server. If the key were in the JavaScript file, anyone
        could open the page source and use it.
        """
        query = request.args.get("q", "").strip()
        # Two letters match too much to be useful and would waste API calls.
        if len(query) < 3:
            return jsonify({"results": []})

        api_key = app.config["GEOAPIFY_API_KEY"]
        if not api_key:
            return jsonify({"results": [], "message": "Location suggestions are unavailable."})

        params = urlencode(
            {
                "text": query,
                "format": "json",
                "lang": "en",
                "limit": 5,
                "apiKey": api_key,
            }
        )
        try:
            with urlopen(
                f"https://api.geoapify.com/v1/geocode/autocomplete?{params}", timeout=4
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        # If Geoapify is down or slow, the organiser can still type the venue by hand.
        # An outside service must not be able to break event creation.
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            app.logger.warning("Geoapify location suggestions were unavailable.")
            return jsonify({"results": [], "message": "Location suggestions are unavailable."}), 502

        # Only the formatted address is passed on. Nothing else from the third-party
        # response reaches the browser.
        results = [
            {"formatted": item["formatted"]}
            for item in payload.get("results", [])
            if item.get("formatted")
        ]
        return jsonify({"results": results})

    @app.route("/events/<int:event_id>/form", methods=("GET", "POST"))
    @login_required
    def edit_form(event_id):
        event = organiser_event_or_404(event_id)
        if request.method == "POST":
            form_title = request.form.get("form_title", "").strip()
            question_text = request.form.get("question_text", "").strip()
            if not form_title or not question_text:
                flash("A form title and the required rating question are needed.", "error")
            else:
                db = get_db()
                db.execute(
                    "UPDATE events SET form_title = ?, question_text = ? WHERE id = ?",
                    (form_title, question_text, event_id),
                )
                db.commit()
                flash("Feedback form saved.", "success")
                return redirect(url_for("edit_form", event_id=event_id))
        return render_template("form_builder.html", event=event)

    @app.post("/events/<int:event_id>/publish")
    @login_required
    def publish_event(event_id):
        organiser_event_or_404(event_id)
        db = get_db()
        db.execute("UPDATE events SET published = 1 WHERE id = ?", (event_id,))
        db.commit()
        flash("Your feedback form is live. Share the public link below.", "success")
        return redirect(url_for("edit_form", event_id=event_id))

    @app.route("/events/<int:event_id>/results")
    @login_required
    def results(event_id):
        event = organiser_event_or_404(event_id)
        db = get_db()
        # SQLite does the counting and the averaging. Doing it in SQL is both faster
        # and shorter than loading every row into Python.
        summary = db.execute(
            "SELECT COUNT(*) AS response_count, AVG(rating) AS average_rating FROM responses WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        # Only responses that actually contain a comment. TRIM and COALESCE together
        # skip both NULL comments and comments that are only spaces.
        comments = db.execute(
            "SELECT rating, comment, created_at FROM responses WHERE event_id = ? AND TRIM(COALESCE(comment, '')) != '' ORDER BY created_at DESC",
            (event_id,),
        ).fetchall()
        return render_template("results.html", event=event, summary=summary, comments=comments)

    @app.route("/feedback/<int:event_id>", methods=("GET", "POST"))
    def feedback(event_id):
        # "AND published = 1" is what keeps a draft form private. An attendee who
        # guesses the URL of an unpublished event gets a 404, not the form.
        event = get_db().execute(
            "SELECT * FROM events WHERE id = ? AND published = 1", (event_id,)
        ).fetchone()
        if event is None:
            abort(404)
        if request.method == "POST":
            rating = request.form.get("rating", "").strip()
            comment = request.form.get("comment", "").strip()
            # Nothing is saved unless the rating is valid. The comment stays optional,
            # because forcing people to write reduces the number of responses.
            if rating not in {"1", "2", "3", "4", "5"}:
                flash("Choose a rating from 1 to 5 before submitting feedback.", "error")
            else:
                db = get_db()
                db.execute(
                    "INSERT INTO responses (event_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                    # An empty comment is stored as NULL rather than "", so the results
                    # query has one thing to check instead of two.
                    (event_id, int(rating), comment or None, utc_now()),
                )
                db.commit()
                # Redirect after a successful POST. Without it, refreshing the page
                # would submit the same response a second time.
                return redirect(url_for("thank_you", event_id=event_id))
        return render_template("feedback.html", event=event)

    @app.route("/feedback/<int:event_id>/thanks")
    def thank_you(event_id):
        event = get_db().execute(
            "SELECT * FROM events WHERE id = ? AND published = 1", (event_id,)
        ).fetchone()
        if event is None:
            abort(404)
        return render_template("thank_you.html", event=event)

    return app


app = create_app()


if __name__ == "__main__":
    # host 0.0.0.0 makes the app answer requests from outside the machine, which the
    # EC2 deployment needs. The port comes from the environment so the same commit
    # runs locally on 5000 and on EC2 on 5001. Before this, the port was edited by
    # hand on the server, which left the deployed file permanently out of step with git.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("EVENTPULSE_PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
