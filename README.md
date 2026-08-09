# EventPulse

EventPulse is an IFN636 Assessment 1 web application for gathering short, anonymous event feedback. An authenticated organiser creates an event, configures and publishes a rating form, and reviews event-level results. An attendee uses a public link to submit a required 1-5 rating and optional comment.

## Current Sprint 1 scope

- Organiser sign-in and protected organiser pages.
- Create an event with a name, date and location.
- Configure a feedback-form title and required rating question.
- Publish a form and share its public attendee URL.
- Submit anonymous feedback with required-rating validation.
- View response count, average rating, comments and an empty-results state.

## Local setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export EVENTPULSE_SECRET_KEY='use-a-long-random-value'
export EVENTPULSE_DEMO_PASSWORD='choose-a-demo-password'
python app.py
```

Open `http://127.0.0.1:5000`.

The seeded organiser is `organiser@eventpulse.local`. Its password is the value of `EVENTPULSE_DEMO_PASSWORD`; for an untouched local demo database it defaults to `eventpulse-demo`.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Architecture

`app.py` contains the routes, access-control guard, SQLite persistence helpers and initial schema. Jinja templates in `templates/` render the organiser and attendee views, while `static/style.css` contains the shared visual system. The SQLite database is stored in Flask's ignored `instance/` folder.

## Security and deployment notes

- `.env`, virtual environments, SQLite data and SSH keys are ignored by Git.
- Set a unique `EVENTPULSE_SECRET_KEY` and `EVENTPULSE_DEMO_PASSWORD` in the EC2 environment; do not use the local defaults.
- The EC2 runbook and public URL will be added only after a genuine deployment is complete.
- This assessment demonstrator uses one seeded organiser and SQLite. It does not provide attendee accounts, ticketing, payments, email/SMS campaigns, or advanced analytics.
