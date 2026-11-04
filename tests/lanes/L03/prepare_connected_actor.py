"""Prepare a synthetic applicant via live Identity APIs; never grant authority.

Requires caller-chosen BT_DEMO_BUYER_EMAIL/PASSWORD. The resulting case still
requires an actual separately authorized L02 reviewer. No access token is printed.
"""

import json
import http.cookiejar
import os
import urllib.request
from urllib.parse import urlsplit
from uuid import uuid4


def main():
    email = os.environ["BT_DEMO_BUYER_EMAIL"]
    if not email.endswith(".test"):
        raise SystemExit("Use only a synthetic .test account")
    origin = os.getenv("BT_CONNECTED_ORIGIN", "http://localhost:3077")
    base = os.getenv("IDENTITY_URL", "http://127.0.0.1:8101")
    url = urlsplit(base)
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "localhost")
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise SystemExit("This check is restricted to the local demo")
    base = base.rstrip("/")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(method, path, body=None, token=None):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Origin": origin,
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid4()),
                **({"Authorization": "Bearer " + token} if token else {}),
            },
        )
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    session = call(
        "POST",
        "/v1/accounts/login",
        {
            "email": email,
            "password": os.environ["BT_DEMO_BUYER_PASSWORD"],
        },
    )
    token = session["access_token"]
    try:
        result = call("GET", "/v1/private-seller/applications/me", token=token)
        if result["application"] is None:
            result = call(
                "POST",
                "/v1/private-seller/applications",
                {
                    "identity_name": "DEMO synthetic watch seller",
                    "contact": email,
                    "payout_reference": "DEMO-L03-SYNTHETIC",
                    "identity_evidence": "DEMO: synthetic identity; no real personal document",
                    "possession_evidence": "DEMO: synthetic possession; no physical inspection claim",
                    "expected_revision": 0,
                },
                token,
            )
        case = result["application"]
        print(
            json.dumps(
                {
                    "sample": True,
                    "subject_id": case["subject_id"],
                    "case_id": case["id"],
                    "revision": case["revision"],
                    "status": case["status"],
                }
            )
        )
    finally:
        call("POST", "/v1/accounts/logout", {}, token)


if __name__ == "__main__":
    main()
