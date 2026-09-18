"""Accounts: what is stored, and what deliberately is not.

The security of this rests on a few specific choices rather than on the flow
working, so these check the choices: that a password cannot be recovered from
what is stored, that the cost parameters travel with each hash so they can be
raised later, that a session token is never stored as itself, and that a reply
never reveals whether an address has an account."""

import contextlib

import pytest
from fastapi.testclient import TestClient

from notekit import accounts, api


class TestPasswordStorage:
    def test_the_password_is_not_in_what_is_stored(self):
        stored = accounts.hash_password("correct horse battery staple")
        assert "correct horse" not in stored
        assert "staple" not in stored

    def test_the_same_password_hashes_differently_each_time(self):
        # Without a per-password salt, one rainbow table covers every account.
        a = accounts.hash_password("same password")
        b = accounts.hash_password("same password")
        assert a != b
        assert accounts.verify_password("same password", a)
        assert accounts.verify_password("same password", b)

    def test_it_verifies_the_right_password_and_only_that(self):
        stored = accounts.hash_password("a real passphrase")
        assert accounts.verify_password("a real passphrase", stored)
        assert not accounts.verify_password("a real passphrasf", stored)
        assert not accounts.verify_password("", stored)

    def test_the_cost_parameters_travel_with_the_hash(self):
        # So today's default can be raised without invalidating old passwords.
        stored = accounts.hash_password("x" * 12)
        scheme, n, r, p, _salt, _key = stored.split("$")
        assert scheme == "scrypt"
        assert int(n) >= 2**14 and int(r) >= 8 and int(p) >= 1

    def test_a_hash_made_with_cheaper_parameters_still_verifies(self):
        import hashlib
        import os

        salt = os.urandom(16)
        n, r, p = 2**12, 8, 1
        key = hashlib.scrypt(b"legacy pass", salt=salt, n=n, r=r, p=p)
        old = f"scrypt${n}${r}${p}${salt.hex()}${key.hex()}"
        assert accounts.verify_password("legacy pass", old)

    @pytest.mark.parametrize("junk", ["", "nonsense", "scrypt$x$y$z$a$b", "bcrypt$1$2$3$4$5"])
    def test_a_malformed_stored_value_fails_rather_than_raises(self, junk):
        assert accounts.verify_password("anything", junk) is False


class TestSessions:
    def test_the_token_is_never_stored_as_itself(self, monkeypatch):
        written = {}

        class Conn:
            def execute(self, sql, params=None):
                if params and "INSERT INTO sessions" in sql:
                    written["params"] = params
                return self

            def fetchone(self):
                return None

            def commit(self):
                pass

        monkeypatch.setattr(accounts.db, "connect", lambda: contextlib.nullcontext(Conn()))
        monkeypatch.setattr(accounts, "ensure_tables", lambda conn: None)
        token = accounts.start_session(1)
        stored = written["params"][0]
        assert token not in stored
        assert len(stored) == 64, "a sha-256 digest, not the token"

    def test_a_token_is_long_enough_to_be_unguessable(self, monkeypatch):
        class Conn:
            def execute(self, *a, **k):
                return self

            def fetchone(self):
                return None

            def commit(self):
                pass

        monkeypatch.setattr(accounts.db, "connect", lambda: contextlib.nullcontext(Conn()))
        monkeypatch.setattr(accounts, "ensure_tables", lambda conn: None)
        tokens = {accounts.start_session(1) for _ in range(5)}
        assert len(tokens) == 5
        assert all(len(t) >= 40 for t in tokens)

    def test_no_token_is_no_user(self):
        assert accounts.session_user(None) is None
        assert accounts.session_user("") is None


class TestKeys:
    def test_the_storage_key_follows_the_row_not_the_address(self):
        # So changing an email later does not orphan a library.
        assert accounts.account_key(7) == "u7"
        assert accounts.account_key(7) != accounts.account_key(8)


class TestApi:
    @pytest.fixture
    def client(self, monkeypatch):
        api._rate_windows.clear()
        monkeypatch.delenv("SITE_PASSWORD", raising=False)
        return TestClient(api.app)

    def test_registering_sets_an_http_only_session_cookie(self, client, monkeypatch):
        monkeypatch.setattr(
            api.accounts, "register",
            lambda e, p, d="": {"id": 3, "email": e, "display_name": d},
        )
        monkeypatch.setattr(api.accounts, "start_session", lambda uid: "tok-123")
        r = client.post("/api/register", json={"email": "a@b.co", "password": "x" * 12})
        assert r.status_code == 200
        assert r.json()["key"] == "u3"
        cookie = r.headers["set-cookie"]
        assert "notekit_session=tok-123" in cookie
        assert "HttpOnly" in cookie, "page scripts must not be able to read it"
        assert "SameSite=lax" in cookie.replace("samesite", "SameSite")

    def test_a_failed_sign_in_does_not_say_which_half_was_wrong(self, client, monkeypatch):
        monkeypatch.setattr(api.accounts, "authenticate", lambda e, p: None)
        r = client.post("/api/login", json={"email": "nobody@b.co", "password": "wrong-one"})
        assert r.status_code == 401
        detail = r.json()["detail"].lower()
        assert "do not match" in detail
        assert "no account" not in detail and "unknown" not in detail

    def test_sign_in_is_rate_limited(self, client, monkeypatch):
        monkeypatch.setattr(api.accounts, "authenticate", lambda e, p: None)
        monkeypatch.setattr(api.config, "RATE_LIMITS", {**api.config.RATE_LIMITS, "login": (2, 900)})
        body = {"email": "a@b.co", "password": "guessing"}
        codes = [client.post("/api/login", json=body).status_code for _ in range(3)]
        assert codes == [401, 401, 429]

    def test_me_answers_without_a_session_rather_than_failing(self, client):
        r = client.get("/api/me")
        assert r.status_code == 200
        assert r.json() == {"signed_in": False}

    def test_a_session_decides_the_caller_over_whatever_the_client_claims(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            api.accounts, "session_user",
            lambda tok: {"id": 9, "email": "a@b.co", "display_name": ""} if tok else None,
        )
        seen = {}
        def record(u):
            seen["user"] = u
            return []

        monkeypatch.setattr(api.courses, "list_for_user", record)
        client.cookies.set("notekit_session", "tok")
        client.get("/api/courses", params={"user": "reader-someone-else"})
        assert seen["user"] == "u9", "the cookie wins over the query parameter"

    def test_without_a_session_a_reader_id_is_still_required(self, client, monkeypatch):
        monkeypatch.setattr(api.accounts, "session_user", lambda tok: None)
        assert client.get("/api/courses/1").status_code == 422


class TestGateAndSignInAreDifferent401s:
    """Both are 401. Conflating them told a reader who mistyped their own
    password to enter the site password instead."""

    @pytest.fixture
    def client(self, monkeypatch):
        api._rate_windows.clear()
        return TestClient(api.app)

    def test_the_instance_gate_marks_its_refusal(self, client, monkeypatch):
        monkeypatch.setenv("SITE_PASSWORD", "hunter2")
        r = client.get("/api/namespaces", params={"user": "x"})
        assert r.status_code == 401
        assert r.headers.get(api.auth.GATE_HEADER) == "1"

    def test_a_failed_sign_in_does_not(self, client, monkeypatch):
        monkeypatch.delenv("SITE_PASSWORD", raising=False)
        monkeypatch.setattr(api.accounts, "authenticate", lambda e, p: None)
        r = client.post("/api/login", json={"email": "a@b.co", "password": "nope-nope-nope"})
        assert r.status_code == 401
        assert api.auth.GATE_HEADER not in r.headers


class TestPasswordReset:
    """A reset link is a way into an account sitting in an inbox, so the rules
    around it matter more than the flow: it works once, it expires, asking for
    one reveals nothing about who has an account, and spending it ends every
    session that existed before."""

    @pytest.fixture
    def client(self, monkeypatch):
        api._rate_windows.clear()
        monkeypatch.delenv("SITE_PASSWORD", raising=False)
        return TestClient(api.app)

    def test_asking_says_the_same_thing_for_an_unknown_address(self, client, monkeypatch):
        sent = []
        monkeypatch.setattr(api.mail, "send", lambda *a, **k: sent.append(a) or True)
        monkeypatch.setattr(api.accounts, "begin_reset", lambda e: None)
        unknown = client.post("/api/password/forgot", json={"email": "nobody@example.com"})

        api._rate_windows.clear()
        monkeypatch.setattr(api.accounts, "begin_reset", lambda e: ("tok", e))
        known = client.post("/api/password/forgot", json={"email": "real@example.com"})

        assert unknown.status_code == known.status_code == 200
        assert unknown.json() == known.json(), "the reply must not reveal which it was"
        assert len(sent) == 1, "but mail only goes to the address that exists"

    def test_the_emailed_link_points_at_the_app_and_carries_the_token(
        self, client, monkeypatch
    ):
        sent = {}
        monkeypatch.setattr(
            api.mail, "send",
            lambda to, subject, body: sent.update(to=to, body=body) or True,
        )
        monkeypatch.setattr(api.accounts, "begin_reset", lambda e: ("tok-abc", e))
        client.post("/api/password/forgot", json={"email": "real@example.com"})
        assert "/reset?token=tok-abc" in sent["body"]
        assert sent["to"] == "real@example.com"

    def test_asking_is_rate_limited_so_it_cannot_pester_an_inbox(self, client, monkeypatch):
        monkeypatch.setattr(api.accounts, "begin_reset", lambda e: None)
        monkeypatch.setattr(api.config, "RATE_LIMITS", {**api.config.RATE_LIMITS, "reset": (2, 3600)})
        body = {"email": "someone@example.com"}
        codes = [client.post("/api/password/forgot", json=body).status_code for _ in range(3)]
        assert codes == [200, 200, 429]

    def test_a_spent_or_unknown_token_is_refused_in_the_same_words(self, client, monkeypatch):
        monkeypatch.setattr(api.accounts, "complete_reset", lambda t, p: False)
        r = client.post("/api/password/reset", json={"token": "nope", "new_password": "x" * 12})
        assert r.status_code == 422
        assert "expired or been used" in r.json()["detail"]

    def test_a_short_new_password_is_refused(self, client, monkeypatch):
        def refuse(token, password):
            raise api.accounts.AccountError("Use at least 10 characters.")

        monkeypatch.setattr(api.accounts, "complete_reset", refuse)
        r = client.post("/api/password/reset", json={"token": "t", "new_password": "short"})
        assert r.status_code == 422

    def test_mail_without_smtp_reports_failure_rather_than_pretending(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("MAIL_FALLBACK_LOG", raising=False)
        from notekit import mail

        assert mail.configured() is False
        assert mail.send("a@b.co", "s", "body") is False
