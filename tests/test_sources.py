"""Sources the reader sees and changes before a course is written."""

import pytest

from notekit import retrieval, sources
from notekit.sources import UnsafeUrl, assert_public_url, html_to_text


class TestPublicUrlGuard:
    """The server fetches whatever address it is given, so the address has
    to be one it is safe to fetch."""

    @pytest.mark.parametrize("url", [
        "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "not a url", "http://",
    ])
    def test_only_http_and_https(self, url):
        with pytest.raises(UnsafeUrl):
            assert_public_url(url)

    @pytest.mark.parametrize("url", [
        "http://localhost:5433/", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/", "http://foo.localhost/",
    ])
    def test_private_loopback_and_metadata_addresses_are_refused(self, url):
        with pytest.raises(UnsafeUrl):
            assert_public_url(url)

    def test_a_name_resolving_to_a_private_address_is_refused(self, monkeypatch):
        # DNS is the usual way round the literal-IP checks.
        monkeypatch.setattr(sources.socket, "getaddrinfo",
                            lambda *a, **k: [(None, None, None, None, ("10.1.2.3", 0))])
        with pytest.raises(UnsafeUrl):
            assert_public_url("http://internal.example.com/")

    def test_a_public_name_passes(self, monkeypatch):
        monkeypatch.setattr(sources.socket, "getaddrinfo",
                            lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 0))])
        assert assert_public_url("https://example.com/page") == "https://example.com/page"


class TestHtmlToText:
    def test_scripts_styles_and_markup_are_dropped(self):
        title, text = html_to_text(
            "<html><head><title> A  Page </title><style>p{}</style></head>"
            "<body><script>var x=1</script><h1>Heading</h1><p>One <b>two</b>.</p>"
            "<p>Three.</p></body></html>"
        )
        assert title == "A Page"
        assert text == "Heading\nOne two.\nThree."

    def test_block_boundaries_become_newlines_and_whitespace_collapses(self):
        _, text = html_to_text("<div>a\n\n   b</div><li>c</li><br>d")
        assert text == "a b\nc\nd"


def test_retrieve_passes_the_exclusion_to_both_searches(monkeypatch):
    seen = {}
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(retrieval.db, "connect", lambda: FakeConn())
    def record(which):
        def fake(conn, **kw):
            seen[which] = kw["exclude"]
            return []
        return fake
    monkeypatch.setattr(retrieval.db, "search_dense", record("dense"))
    monkeypatch.setattr(retrieval.db, "search_sparse", record("sparse"))
    monkeypatch.setattr(retrieval.embedding, "embed_query", lambda q, cfg: [0.0])
    assert retrieval.retrieve(query="q", namespace="ns", exclude=[7, 9]) == []
    assert seen == {"dense": [7, 9], "sparse": [7, 9]}
