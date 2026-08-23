import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app import create_app


class EventPulseTestCase(unittest.TestCase):
    """Acceptance tests for the two workflows in the EventPulse scope.

    Each test creates its own throwaway SQLite file, so tests cannot affect each
    other and none of them touch the real database.
    """

    def setUp(self):
        self.database = tempfile.NamedTemporaryFile(delete=False)
        self.database.close()
        self.app = create_app(
            {"TESTING": True, "DATABASE": self.database.name, "SECRET_KEY": "test-secret", "DEMO_PASSWORD": "test-password"}
        )
        self.client = self.app.test_client()

    def tearDown(self):
        os.unlink(self.database.name)

    def login(self):
        return self.client.post(
            "/login",
            data={"email": "organiser@eventpulse.local", "password": "test-password"},
            follow_redirects=True,
        )

    def create_and_publish_event(self):
        self.login()
        response = self.client.post(
            "/events/new",
            data={"name": "Campus Design Night", "event_date": "2026-09-01", "location": "QUT Gardens Point"},
            follow_redirects=False,
        )
        event_id = int(response.headers["Location"].split("/")[2])
        self.client.post(
            f"/events/{event_id}/form",
            data={"form_title": "Tell us about the night", "question_text": "Rate the event overall"},
        )
        self.client.post(f"/events/{event_id}/publish")
        return event_id

    def test_start_page_offers_both_roles(self):
        """The home page shows both roles, and says so when no form is published yet."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"I&rsquo;m an organiser", response.data)
        self.assertIn(b"I&rsquo;m an attendee", response.data)
        self.assertIn(b"No feedback form is published yet.", response.data)

    def test_start_page_links_to_published_form(self):
        """Once a form is published, the attendee card links straight to it."""
        event_id = self.create_and_publish_event()
        response = self.client.get("/")
        self.assertIn(f"/feedback/{event_id}".encode(), response.data)

    def test_event_list_shows_response_count(self):
        """The organiser sees how many responses each event has collected."""
        event_id = self.create_and_publish_event()
        self.client.post(f"/feedback/{event_id}", data={"rating": "4", "comment": "Good"})
        response = self.client.get("/events")
        self.assertIn(b"1 response", response.data)

    def test_event_search_matches_name(self):
        """Searching narrows the list by name, and no match shows a clear message."""
        self.create_and_publish_event()
        self.client.post(
            "/events/new",
            data={"name": "Industry Night", "event_date": "2026-10-02", "location": "Kelvin Grove"},
        )
        matched = self.client.get("/events?q=Industry")
        self.assertIn(b"Industry Night", matched.data)
        self.assertNotIn(b"Campus Design Night", matched.data)

        empty = self.client.get("/events?q=NoSuchEvent")
        self.assertIn(b"No events match this search", empty.data)

    def test_protected_events_redirect_to_login(self):
        """FR 01: a visitor who is not signed in cannot reach organiser pages."""
        response = self.client.get("/events")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_required_event_fields_show_validation(self):
        """FR 02: an event will not save without a name, a date and a location."""
        self.login()
        response = self.client.post("/events/new", data={"name": "", "event_date": "", "location": ""}, follow_redirects=True)
        self.assertIn(b"Event name, date, and location are all required.", response.data)

    def test_location_suggestions_require_sign_in(self):
        """The Geoapify proxy is behind the sign-in guard, so the key cannot be used
        by an anonymous visitor to make free API calls."""
        response = self.client.get("/api/location-suggestions?q=QUT")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    @patch("app.urlopen")
    def test_location_suggestions_proxy_formatted_results(self, mocked_urlopen):
        """Geoapify is replaced by a fake here. The test checks our own code, and it
        keeps the suite working offline and free of real API calls."""
        self.app.config["GEOAPIFY_API_KEY"] = "test-key"
        response_object = MagicMock()
        response_object.read.return_value = b'{"results": [{"formatted": "QUT Gardens Point, Brisbane QLD, Australia"}]}'
        mocked_urlopen.return_value.__enter__.return_value = response_object

        self.login()
        response = self.client.get("/api/location-suggestions?q=QUT Gardens")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"results": [{"formatted": "QUT Gardens Point, Brisbane QLD, Australia"}]},
        )
        self.assertIn("apiKey=test-key", mocked_urlopen.call_args.args[0])

    def test_feedback_validation_persistence_and_results(self):
        """FR 06 to FR 09: a missing rating saves nothing, a valid response is stored,
        and the organiser then sees the count and the average."""
        event_id = self.create_and_publish_event()
        invalid = self.client.post(f"/feedback/{event_id}", data={"comment": "Good session"}, follow_redirects=True)
        self.assertIn(b"Choose a rating from 1 to 5", invalid.data)
        valid = self.client.post(
            f"/feedback/{event_id}", data={"rating": "5", "comment": "Great presenters"}, follow_redirects=True
        )
        self.assertIn(b"Feedback received", valid.data)
        results = self.client.get(f"/events/{event_id}/results")
        self.assertIn(b">1<", results.data)
        self.assertIn(b"5.0", results.data)
        self.assertIn(b"Great presenters", results.data)


if __name__ == "__main__":
    unittest.main()
