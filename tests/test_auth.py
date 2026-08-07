"""The shared password gate. It is a lock on the front door, not
authentication — see auth.py's own docstring — but the lock itself has to
actually work: wrong passwords rejected, tokens forgeable only with the
password, timing-safe comparison, and the gate fully inert when unset."""

import pytest

from notekit import auth


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("SITE_PASSWORD", raising=False)


def test_gate_is_off_by_default():
    assert auth.enabled() is False
    assert auth.password() is None


def test_gate_turns_on_when_the_env_var_is_set(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    assert auth.enabled() is True
    assert auth.password() == "hunter2"


def test_blank_password_is_treated_as_unset(monkeypatch):
    # An empty or whitespace-only value must not silently gate the app with
    # an unguessable-but-also-uncheckable password.
    monkeypatch.setenv("SITE_PASSWORD", "   ")
    assert auth.enabled() is False


@pytest.mark.parametrize("candidate", ["anything", "", "hunter2 "])
def test_check_password_always_true_when_gate_is_off(candidate):
    assert auth.check_password(candidate) is True


def test_check_password_accepts_the_right_password(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    assert auth.check_password("hunter2") is True


def test_check_password_rejects_the_wrong_password(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    assert auth.check_password("hunter3") is False
    assert auth.check_password("") is False


def test_check_password_tolerates_surrounding_whitespace(monkeypatch):
    # The candidate is what a browser sends; trimming it is the forgiving
    # side of the comparison. The stored password itself is not re-trimmed.
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    assert auth.check_password("  hunter2  ") is True


def test_token_is_deterministic_and_password_specific():
    a1 = auth.token_for("hunter2")
    a2 = auth.token_for("hunter2")
    b = auth.token_for("different")
    assert a1 == a2
    assert a1 != b


def test_check_token_always_true_when_gate_is_off():
    assert auth.check_token(None) is True
    assert auth.check_token("garbage") is True


def test_check_token_accepts_a_token_derived_from_the_real_password(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    token = auth.token_for("hunter2")
    assert auth.check_token(token) is True


def test_check_token_rejects_a_forged_or_missing_token(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    assert auth.check_token(None) is False
    assert auth.check_token("") is False
    assert auth.check_token(auth.token_for("wrong-password")) is False


def test_rotating_the_password_invalidates_the_old_token(monkeypatch):
    monkeypatch.setenv("SITE_PASSWORD", "hunter2")
    old_token = auth.token_for("hunter2")

    monkeypatch.setenv("SITE_PASSWORD", "rotated-password")
    assert auth.check_token(old_token) is False
    assert auth.check_token(auth.token_for("rotated-password")) is True


def test_health_and_auth_endpoints_are_always_open():
    # If these ever fell out of OPEN_PATHS, a deployed instance's platform
    # health check would start failing and the service would restart forever.
    assert "/api/health" in auth.OPEN_PATHS
    assert "/api/auth" in auth.OPEN_PATHS
