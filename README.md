# EventPulse

EventPulse is an IFN636 Assessment 1 web application for gathering short, anonymous event feedback. An authenticated organiser creates an event, configures and publishes a rating form, and reviews event-level results. An attendee uses a public link to submit a required 1-5 rating and an optional comment.

**Live deployment:** http://52.62.63.13:5001/
**EC2 instance:** `i-0d6a1b603d0a1e905` (REZ-Shiraz), region `ap-southeast-2`

## Scope

Two roles and two complete workflows.

**Organiser** — signs in, creates an event, configures the rating question, publishes the form, reads the results.
**Attendee** — opens the public link, submits an anonymous rating and an optional comment.

Implemented:

- Role selection landing page for both paths.
- Organiser sign-in and protected organiser pages.
- Create an event with a name, date and location.
- Venue suggestions in the location field through Geoapify Address Autocomplete.
- Configure a feedback form title and the required rating question.
- Publish a form and share its public attendee URL.
- Submit anonymous feedback, with validation when no rating is chosen.
- Response count and search on the event list.
- Response count, average rating, comments, and an empty results state.

Out of scope by choice: attendee accounts, organiser self-registration, ticketing, payments, email or SMS campaigns, and analytics beyond count and average.

## Local setup

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export EVENTPULSE_SECRET_KEY='use-a-long-random-value'
export EVENTPULSE_DEMO_PASSWORD='choose-a-demo-password'
export GEOAPIFY_API_KEY='your-geoapify-key'
python app.py
```

Open `http://127.0.0.1:5000`.

The seeded organiser is `organiser@eventpulse.local`. Its password is the value of `EVENTPULSE_DEMO_PASSWORD`, which defaults to `eventpulse-demo` on an untouched local database.

The Geoapify key is optional. Without it the organiser types the venue by hand and everything else works.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Nine tests cover the sign-in guard, event validation, the Geoapify proxy, the attendee validation and persistence path, the results summary, and the landing page.

Use the project virtual environment. A globally installed Flask and Werkzeug pair can be incompatible and fails with `Response.set_cookie() got an unexpected keyword argument 'partitioned'`. That is an environment fault, not an application fault.

## Architecture

Flask with Jinja templates and SQLite. One process, one file-based database, no build step.

- `app.py` holds the routes, the `login_required` guard, the SQLite helpers and the schema.
- `templates/` renders the organiser and attendee views.
- `static/style.css` holds the shared visual system; `static/location_autocomplete.js` drives the venue suggestions.
- The SQLite file lives in Flask's `instance/` folder, which Git ignores.

Three tables:

| Table | Holds |
| --- | --- |
| `organisers` | the seeded organiser email and password hash |
| `events` | organiser, name, date, location, form title, question, published flag |
| `responses` | event, rating 1-5, optional comment, UTC timestamp |

Four data operations: create an event, update and publish a form, create a response, read the event list and the result summaries.

## Deployment

Manual deployment to EC2. There is no CI or CD, which the assessment allows.

```bash
# on the instance, through AWS Session Manager
cd ~/ifn636-eventpulse
git pull
export EVENTPULSE_PORT=5001
setsid nohup .venv/bin/python app.py > ~/eventpulse.log 2>&1 < /dev/null &
ss -ltn | grep 5001
```

The port comes from `EVENTPULSE_PORT` so the same commit runs on 5000 locally and 5001 on EC2. Earlier the port was edited by hand on the server, which left the deployed file permanently out of step with the repository.

An Elastic IP is attached, so the public address survives a stop and a start.

## Security

- `.env`, virtual environments, the SQLite database and SSH keys are all ignored by Git. No secret is committed.
- Organiser routes sit behind a session guard. Every organiser query filters by organiser identity, so changing the number in a URL cannot reach another organiser's event.
- An attendee link only opens an event with `published = 1`. A draft returns 404.
- The rating must be 1 to 5. Python checks it, and the `responses` table repeats the rule as a `CHECK` constraint.
- The Geoapify key stays on the server. The browser calls `/api/location-suggestions` and never sees the key.
- Inbound access on EC2 is limited to TCP 5001 from single addresses. Nothing else is opened.

## Known limitations

- The application runs on the Flask development server. A production deployment would use gunicorn behind nginx.
- Traffic is HTTP, not HTTPS.
- SQLite accepts one writer at a time. That suits this scale and would not suit a busy production system.
- The attendee card on the landing page links to the newest published event. That is a convenience for the demonstration, not real attendee behaviour, which is to follow a link the organiser shares.
- The V2 Figma prototype also shows sidebar navigation, a status filter, a Settings page and an Insights view. Those stay as design intent for a later iteration.
- The service does not restart by itself after a reboot.
