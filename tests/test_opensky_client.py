import pytest
import requests
import responses
from responses import matchers

from extract.config import BoundingBox, Settings
from extract.opensky_client import API_URL, TOKEN_URL, OpenSkyClient, OpenSkyError

STATES_URL = f"{API_URL}/states/all"
CREDS = Settings(client_id="id", client_secret="secret")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_client(sleeps, clock):
    def _make(settings=None, **kwargs):
        kwargs.setdefault("max_retries", 3)
        return OpenSkyClient(settings or Settings(), sleep=sleeps.append, clock=clock, **kwargs)

    return _make


def add_token(rsps, token="tok-1", expires_in=1800):
    rsps.post(TOKEN_URL, json={"access_token": token, "expires_in": expires_in})


@pytest.fixture
def rsps():
    with responses.RequestsMock() as mock:
        yield mock


class TestGetStates:
    def test_anonymous_request_has_no_auth(self, rsps, make_client, api_payload):
        rsps.get(STATES_URL, json=api_payload)
        snapshot = make_client().get_states()
        assert len(snapshot.states) == 2
        assert "Authorization" not in rsps.calls[0].request.headers
        assert rsps.calls[0].request.url == STATES_URL  # no bbox params

    def test_bbox_sent_as_query_params(self, rsps, make_client, api_payload):
        rsps.get(
            STATES_URL,
            json=api_payload,
            match=[matchers.query_param_matcher({"lamin": "45.8", "lomin": "5.9", "lamax": "47.8", "lomax": "10.5"})],
        )
        make_client().get_states(BoundingBox(45.8, 5.9, 47.8, 10.5))

    def test_falls_back_to_settings_bbox(self, rsps, make_client, api_payload):
        rsps.get(STATES_URL, json=api_payload, match=[matchers.query_param_matcher({"lamin": "1", "lomin": "2", "lamax": "3", "lomax": "4"})])
        make_client(Settings(bbox=BoundingBox(1, 2, 3, 4))).get_states()

    def test_argument_bbox_overrides_settings(self, rsps, make_client, api_payload):
        rsps.get(STATES_URL, json=api_payload, match=[matchers.query_param_matcher({"lamin": "10", "lomin": "20", "lamax": "30", "lomax": "40"})])
        make_client(Settings(bbox=BoundingBox(1, 2, 3, 4))).get_states(BoundingBox(10, 20, 30, 40))

    def test_passes_timeout(self, make_client, api_payload):
        session = requests.Session()
        seen = {}

        def fake_get(url, **kwargs):
            seen.update(kwargs)
            resp = requests.Response()
            resp.status_code = 200
            resp._content = b'{"time": 1, "states": null}'
            return resp

        session.get = fake_get
        OpenSkyClient(Settings(), session=session, timeout=7).get_states()
        assert seen["timeout"] == 7

    def test_null_states(self, rsps, make_client):
        rsps.get(STATES_URL, json={"time": 1, "states": None})
        assert make_client().get_states().states == []


class TestErrors:
    @pytest.mark.parametrize("status", [400, 403, 404])
    def test_client_errors_are_not_retried(self, rsps, make_client, sleeps, status):
        rsps.get(STATES_URL, status=status, body="nope")
        with pytest.raises(OpenSkyError, match=f"HTTP {status}"):
            make_client().get_states()
        assert len(rsps.calls) == 1
        assert sleeps == []

    def test_anonymous_401_not_retried(self, rsps, make_client):
        rsps.get(STATES_URL, status=401)
        with pytest.raises(OpenSkyError, match="HTTP 401"):
            make_client().get_states()
        assert len(rsps.calls) == 1

    def test_invalid_json(self, rsps, make_client):
        rsps.get(STATES_URL, body="<html>maintenance</html>")
        with pytest.raises(OpenSkyError, match="not valid JSON"):
            make_client().get_states()

    def test_unexpected_shape(self, rsps, make_client):
        rsps.get(STATES_URL, json={"states": []})
        with pytest.raises(OpenSkyError, match="unexpected response shape"):
            make_client().get_states()


class TestRetries:
    @pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
    def test_retries_transient_status_then_succeeds(self, rsps, make_client, sleeps, api_payload, status):
        rsps.get(STATES_URL, status=status)
        rsps.get(STATES_URL, json=api_payload)
        assert len(make_client().get_states().states) == 2
        assert sleeps == [1.0]

    def test_exponential_backoff(self, rsps, make_client, sleeps, api_payload):
        for _ in range(3):
            rsps.get(STATES_URL, status=503)
        rsps.get(STATES_URL, json=api_payload)
        make_client(backoff=0.5).get_states()
        assert sleeps == [0.5, 1.0, 2.0]

    def test_gives_up_after_max_retries(self, rsps, make_client, sleeps):
        rsps.get(STATES_URL, status=503)
        with pytest.raises(OpenSkyError, match="HTTP 503 .* after 3 attempts"):
            make_client(max_retries=2).get_states()
        assert len(rsps.calls) == 3
        assert len(sleeps) == 2

    def test_zero_retries(self, rsps, make_client, sleeps):
        rsps.get(STATES_URL, status=500)
        with pytest.raises(OpenSkyError):
            make_client(max_retries=0).get_states()
        assert len(rsps.calls) == 1
        assert sleeps == []

    def test_honours_rate_limit_retry_after_header(self, rsps, make_client, sleeps, api_payload):
        rsps.get(STATES_URL, status=429, headers={"X-Rate-Limit-Retry-After-Seconds": "42"})
        rsps.get(STATES_URL, json=api_payload)
        make_client().get_states()
        assert sleeps == [42.0]

    def test_ignores_garbage_retry_after_header(self, rsps, make_client, sleeps, api_payload):
        rsps.get(STATES_URL, status=429, headers={"X-Rate-Limit-Retry-After-Seconds": "soon"})
        rsps.get(STATES_URL, json=api_payload)
        make_client().get_states()
        assert sleeps == [1.0]

    @pytest.mark.parametrize("exc", [requests.ConnectionError("down"), requests.Timeout("slow")])
    def test_retries_network_errors(self, rsps, make_client, sleeps, api_payload, exc):
        rsps.get(STATES_URL, body=exc)
        rsps.get(STATES_URL, json=api_payload)
        assert len(make_client().get_states().states) == 2
        assert sleeps == [1.0]

    def test_network_error_exhausts_retries(self, rsps, make_client):
        rsps.get(STATES_URL, body=requests.ConnectionError("down"))
        with pytest.raises(OpenSkyError, match="after 2 attempts"):
            make_client(max_retries=1).get_states()


class TestAuth:
    def test_fetches_token_and_sends_bearer(self, rsps, make_client, api_payload):
        rsps.post(
            TOKEN_URL,
            json={"access_token": "tok-1", "expires_in": 1800},
            match=[matchers.urlencoded_params_matcher(
                {"grant_type": "client_credentials", "client_id": "id", "client_secret": "secret"}
            )],
        )
        rsps.get(STATES_URL, json=api_payload, match=[matchers.header_matcher({"Authorization": "Bearer tok-1"})])
        make_client(CREDS).get_states()

    def test_reuses_token_until_near_expiry(self, rsps, make_client, clock, api_payload):
        add_token(rsps, "tok-1", expires_in=1800)
        rsps.get(STATES_URL, json=api_payload)
        client = make_client(CREDS)
        client.get_states()
        clock.now += 1700  # still inside the 1800 - 60s window
        client.get_states()
        assert sum(c.request.url == TOKEN_URL for c in rsps.calls) == 1

    def test_refreshes_token_before_expiry(self, rsps, make_client, clock, api_payload):
        add_token(rsps, "tok-1")
        rsps.get(STATES_URL, json=api_payload)
        client = make_client(CREDS)
        client.get_states()
        clock.now += 1741  # past expiry minus refresh margin
        rsps.replace(responses.POST, TOKEN_URL, json={"access_token": "tok-2", "expires_in": 1800})
        client.get_states()
        assert rsps.calls[-1].request.headers["Authorization"] == "Bearer tok-2"

    def test_short_lived_token_is_always_refreshed(self, rsps, make_client, api_payload):
        add_token(rsps, expires_in=30)  # shorter than the refresh margin
        rsps.get(STATES_URL, json=api_payload)
        client = make_client(CREDS)
        client.get_states()
        client.get_states()
        assert sum(c.request.url == TOKEN_URL for c in rsps.calls) == 2

    def test_defaults_expiry_when_missing(self, rsps, make_client, clock, api_payload):
        rsps.post(TOKEN_URL, json={"access_token": "tok-1"})
        rsps.get(STATES_URL, json=api_payload)
        client = make_client(CREDS)
        client.get_states()
        clock.now += 1000
        client.get_states()
        assert sum(c.request.url == TOKEN_URL for c in rsps.calls) == 1

    def test_401_triggers_single_token_refresh(self, rsps, make_client, api_payload):
        add_token(rsps, "tok-1")
        rsps.get(STATES_URL, status=401)
        rsps.get(STATES_URL, json=api_payload)
        client = make_client(CREDS)
        client.get_states()
        token_calls = [c for c in rsps.calls if c.request.url == TOKEN_URL]
        assert len(token_calls) == 2

    def test_repeated_401_gives_up(self, rsps, make_client):
        add_token(rsps)
        rsps.get(STATES_URL, status=401)
        with pytest.raises(OpenSkyError, match="HTTP 401"):
            make_client(CREDS).get_states()
        assert sum(c.request.url == STATES_URL for c in rsps.calls) == 2

    def test_token_endpoint_rejects_credentials(self, rsps, make_client):
        rsps.post(TOKEN_URL, status=401, json={"error": "invalid_client"})
        with pytest.raises(OpenSkyError, match="token request failed with HTTP 401"):
            make_client(CREDS).get_states()

    @pytest.mark.parametrize("body", [{}, {"token": "x"}, "not json"])
    def test_malformed_token_response(self, rsps, make_client, body):
        if isinstance(body, str):
            rsps.post(TOKEN_URL, body=body)
        else:
            rsps.post(TOKEN_URL, json=body)
        with pytest.raises(OpenSkyError, match="missing access_token"):
            make_client(CREDS).get_states()

    def test_token_endpoint_unreachable(self, rsps, make_client):
        rsps.post(TOKEN_URL, body=requests.ConnectionError("dns"))
        with pytest.raises(OpenSkyError, match="could not reach token endpoint"):
            make_client(CREDS).get_states()

    def test_secret_not_in_error_messages(self, rsps, make_client):
        rsps.post(TOKEN_URL, status=500, body="internal")
        with pytest.raises(OpenSkyError) as exc_info:
            make_client(Settings(client_id="id", client_secret="super-secret")).get_states()
        assert "super-secret" not in str(exc_info.value)
