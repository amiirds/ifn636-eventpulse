# EventPulse

EventPulse collects short anonymous feedback after an event. An organiser signs in, sets up a form and reads the results. An attendee gets a link, picks a rating from 1 to 5, and can add a comment.

Built for IFN636 Assessment 1.

**Live deployment:** http://52.62.63.13:5001/
**EC2 instance:** `i-0d6a1b603d0a1e905` (REZ-Shiraz), region `ap-southeast-2`

## Scope

Two roles and two complete workflows.

Organiser: signs in, creates an event, sets the rating question, publishes the form, reads results.

Attendee: opens the public link, leaves a rating and maybe a comment.

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
sudo systemctl restart eventpulse
systemctl is-active eventpulse
```

The app runs as a systemd service, `/etc/systemd/system/eventpulse.service`:

```ini
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/ifn636-eventpulse
Environment=EVENTPULSE_PORT=5001
ExecStart=/home/ubuntu/ifn636-eventpulse/.venv/bin/python app.py
Restart=always
RestartSec=5
```

It was started by hand with `nohup` at first. That did not survive a reboot, and the instance restarted twice, so the app was found stopped both times. systemd starts it on boot and restarts it within five seconds if it dies.

Secrets live in `/home/ubuntu/ifn636-eventpulse/.env` on the instance, mode 600, owned by `ubuntu`. That file sets `EVENTPULSE_SECRET_KEY`, `EVENTPULSE_DEMO_PASSWORD` and `GEOAPIFY_API_KEY`. None of the code defaults are used in the deployment.

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
- No CSRF token on any POST route. A signed-in organiser could be made to publish a draft or sign out by a crafted page on another site.
- No rate limit on sign in. Nothing slows down repeated password guesses.
- Publishing is one way. There is no unpublish route, so a live form stays live.
- Nothing stops one attendee submitting many responses. Anonymity was chosen over deduplication, and that trade is deliberate.
- The seeded organiser is the only account. There is no delete operation on any record.

- The application runs on the Flask development server. A production deployment would use gunicorn behind nginx.
- Traffic is HTTP, not HTTPS.
- SQLite takes one writer at a time. Fine for a demo, wrong for anything busy.
- The attendee card on the landing page just links to the newest published event. That is a shortcut for the demo. In practice the organiser sends the link.
- The V2 Figma prototype also shows sidebar navigation, a status filter, a Settings page and an Insights view. Those stay as design intent for a later iteration.
