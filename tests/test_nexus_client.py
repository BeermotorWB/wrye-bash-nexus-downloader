"""Nexus API client: identity headers, rate limits, errors, GraphQL, CDN.
Mirrors the Go version's ratelimit_test.go and nexus_test.go."""
import json

import pytest

import nexus_client
from nexus_client import (NexusAPIError, NexusClient, RateLimitedError,
                          content_disposition_file_name)
from tests.conftest import reply

SKSE_FILE_NAME = "Skyrim Script Extender (SKSE64) Steam 30379 2.3.1 2026-08-27T16-52Z s6Og0dG94.7z"


def client_for(url: str) -> NexusClient:
    c = NexusClient("test-key")
    c.host = url
    c.retry_delay = 0
    return c


def rate_headers(hourly: str, daily: str) -> dict:
    """x-rl-* as the v1 API sends them (v1_download_link.json)."""
    return {"x-rl-hourly-remaining": hourly, "x-rl-hourly-reset": "2026-09-30 15:00:00 +0000",
            "x-rl-daily-remaining": daily, "x-rl-daily-reset": "2026-10-01 00:00:00 +0000"}


def test_api_headers(http_server, monkeypatch):
    monkeypatch.setattr(nexus_client, "VERSION", "9.9.9")
    srv, url = http_server(lambda req: reply(req, body=b"{}"))
    client_for(url).file_details("skyrimspecialedition", 30379, 795992)
    h = srv.requests[0].headers
    assert h["apikey"] == "test-key"
    assert h["Protocol-Version"] == "1.7.3"
    assert h["Application-Name"] == "WBNXMLink"
    assert h["Application-Version"] == "9.9.9"
    assert h["User-Agent"].startswith("WBNXMLink/9.9.9 (") and ") Python/" in h["User-Agent"]


def test_retry_after_429(http_server):
    def handler(req):
        n = len(req.server.requests)
        if n <= 2:
            reply(req, 429, headers=rate_headers("1990", "19990"))
        else:
            reply(req, body=b'{"file_id": 795992, "uid": 7318625068376, "file_name": "a.7z"}')
    srv, url = http_server(handler)
    fi = client_for(url).file_details("skyrimspecialedition", 30379, 795992)
    assert (fi.file_id, fi.uid, fi.file_name) == (795992, 7318625068376, "a.7z")
    assert len(srv.requests) == 3  # 2 retries


def test_retry_gives_up(http_server):
    srv, url = http_server(lambda req: reply(req, 429, headers=rate_headers("1990", "19990")))
    with pytest.raises(RateLimitedError):
        client_for(url).file_details("skyrimspecialedition", 30379, 795992)
    assert len(srv.requests) == 1 + nexus_client.MAX_RATE_LIMIT_RETRIES


def test_exhausted_budget_stops_requests(http_server):
    """Once the budget is used up, nothing more is sent (nexus-api Quota.block)."""
    srv, url = http_server(lambda req: reply(req, 429, headers=rate_headers("0", "0")))
    c = client_for(url)
    with pytest.raises(RateLimitedError, match="2026-09-30 15:00:00 \\+0000"):
        c.file_details("skyrimspecialedition", 30379, 795992)
    with pytest.raises(RateLimitedError):
        c.generate_download_link("skyrimspecialedition", 30379, 795992)
    assert len(srv.requests) == 1
    lim = c.limits()
    assert lim.known and lim.hourly_remaining == 0 and lim.daily_remaining == 0


def test_403_is_typed(http_server):
    """A free account's keyless download_link: the collection flow stops on it."""
    srv, url = http_server(lambda req: reply(req, 403, body=b'{"message":"forbidden"}'))
    with pytest.raises(NexusAPIError) as e:
        client_for(url).generate_download_link("skyrimspecialedition", 30379, 795992)
    assert e.value.status == 403
    assert str(e.value) == 'Nexus API Error 403: {"message":"forbidden"}'
    assert len(srv.requests) == 1  # a 403 is not retried


def test_graphql_retry_resends_body(http_server):
    def handler(req):
        assert b"collectionRevision" in req.body
        assert req.headers["Protocol-Version"] == "1.7.3"
        if len(req.server.requests) == 1:
            reply(req, 429)
            return
        reply(req, body=json.dumps({"data": {"collectionRevision": {
            "id": 797763, "revisionNumber": 325,
            "downloadLink": "/v2/collections/49623/revisions/797763/download_link",
            "collection": {"slug": "xk05aw", "name": "Essential Mods for Skyrim",
                           "game": {"domainName": "skyrimspecialedition"}},
            "modFiles": [{"file": {"modId": 30379, "fileId": 795992, "name": "SKSE",
                                   "version": "2.3.1", "date": 1787849567,
                                   "uid": "7318625068376", "sizeInBytes": "952607",
                                   "game": {"domainName": "skyrimspecialedition"}}}]}}}).encode())
    srv, url = http_server(handler)
    rev = client_for(url).get_collection_revision("xk05aw", 325)
    assert rev.revision_number == 325 and rev.collection_slug == "xk05aw"
    f = rev.mod_files[0]
    # GraphQL serves uid and sizeInBytes as strings
    assert (f.uid, f.size_in_bytes) == (7318625068376, 952607)


@pytest.mark.parametrize("header, want", [
    # verbatim from the Nexus CDN, 2026-09-30
    (f'attachment; filename="{SKSE_FILE_NAME}"', SKSE_FILE_NAME),
    ("attachment; filename*=UTF-8''Caf%C3%A9%20Mod.zip", "Café Mod.zip"),
    ("attachment", ""),
    ("", ""),
])
def test_content_disposition_file_name(header, want):
    assert content_disposition_file_name(header) == want


def test_cdn_file_name(http_server):
    def handler(req):
        assert req.command == "HEAD"
        # CDN requests carry none of the API identity headers, as in Vortex
        assert "apikey" not in req.headers and "Application-Name" not in req.headers
        if req.path == "/missing":
            reply(req)
        else:
            reply(req, headers={"Content-Disposition": f'attachment; filename="{SKSE_FILE_NAME}"'})
    srv, url = http_server(handler)
    c = NexusClient("")
    assert c.cdn_file_name(url + "/7d/ee/b7/7deeb793") == SKSE_FILE_NAME
    with pytest.raises(RuntimeError):
        c.cdn_file_name(url + "/missing")


def test_resolve_collection_download(http_server):
    srv, url = http_server(lambda req: reply(req, body=json.dumps(
        {"download_links": [{"name": "LA", "short_name": "LA", "URI": "https://cdn/x"}]}).encode()))
    links = client_for(url).resolve_collection_download("/v2/collections/1/revisions/2/download_link")
    assert [l.uri for l in links] == ["https://cdn/x"]
    assert srv.requests[0].headers["Application-Name"] == "WBNXMLink"
