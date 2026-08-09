"""EventPulse - a focused Flask event-feedback demonstrator for IFN636."""

import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


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
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("EVENTPULSE_SECRET_KEY", "development-only-change-me"),
        DATABASE=str(Path(app.instance_path) / "eventpulse.sqlite"),
        DEMO_PASSWORD=os.environ.get("EVENTPULSE_DEMO_PASSWORD", "eventpulse-demo"),
    )
    if test_config:
        app.config.update(test_config)

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
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
        db = get_db()
        exists = db.execute(
            "SELECT id FROM organisers WHERE email = ?", ("organiser@eventpulse.local",)
        ).fetchone()
        if exists is None:
            db.execute(
                "INSERT INTO organisers (email, password_hash) VALUES (?, ?)",
                (
                    "organiser@eventpulse.local",
                    generate_password_hash(app.config["DEMO_PASSWORD"]),
                ),
            )
            db.commit()

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()
        seed_demo_organiser()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "organiser_id" not in session:
                flash("Please sign in to access organiser tools.", "error")
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    def organiser_event_or_404(event_id):
        event = get_db().execute(
            "SELECT * FROM events WHERE id = ? AND organiser_id = ?",
            (event_id, session["organiser_id"]),
        ).fetchone()
        if event is None:
            abort(404)
        return event

    @app.route("/")
    def index():
        return redirect(url_for("events") if "organiser_id" in session else url_for("login"))

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
            if organiser is None or not check_password_hash(organiser["password_hash"], password):
                flash("Email or password was not recognised.", "error")
            else:
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
        rows = get_db().execute(
            "SELECT * FROM events WHERE organiser_id = ? ORDER BY created_at DESC",
            (session["organiser_id"],),
        ).fetchall()
        return render_template("events.html", events=rows)

    @app.route("/events/new", methods=("GET", "POST"))
    @login_required
    def create_event():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            event_date = request.form.get("event_date", "")
            location = request.form.get("location", "").strip()
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
        summary = db.execute(
            "SELECT COUNT(*) AS response_count, AVG(rating) AS average_rating FROM responses WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        comments = db.execute(
            "SELECT rating, comment, created_at FROM responses WHERE event_id = ? AND TRIM(COALESCE(comment, '')) != '' ORDER BY created_at DESC",
            (event_id,),
        ).fetchall()
        return render_template("results.html", event=event, summary=summary, comments=comments)

    @app.route("/feedback/<int:event_id>", methods=("GET", "POST"))
    def feedback(event_id):
        event = get_db().execute(
            "SELECT * FROM events WHERE id = ? AND published = 1", (event_id,)
        ).fetchone()
        if event is None:
            abort(404)
        if request.method == "POST":
            rating = request.form.get("rating", "").strip()
            comment = request.form.get("comment", "").strip()
            if rating not in {"1", "2", "3", "4", "5"}:
                flash("Choose a rating from 1 to 5 before submitting feedback.", "error")
            else:
                db = get_db()
                db.execute(
                    "INSERT INTO responses (event_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, int(rating), comment or None, utc_now()),
                )
                db.commit()
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
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
