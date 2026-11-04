"""Real isolated review/onboarding and twice-run licensed Catalog import.

Run after the explicitly authorized Identity-local initial-principal bootstrap.
Only HTTP commands cross domain boundaries. No verdict or financial state is
seeded, and credentials/private evidence never enter this proof's output.
"""

import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
IDENTITY = "http://127.0.0.1:43101"
CATALOG = "http://127.0.0.1:43102"


class Actor:
    def __init__(self, credentials):
        self.credentials = credentials
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.session = None

    def request(self, method, path, body=None, *, key=None, base=IDENTITY, raw=False):
        headers = {"Origin": "http://localhost:3077", "Content-Type": "application/json"}
        if self.session:
            headers["Authorization"] = "Bearer " + self.session["access_token"]
        if method != "GET":
            headers["Idempotency-Key"] = key or str(uuid4())
        request = urllib.request.Request(
            base + path, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None
        )
        with self.http.open(request, timeout=20) as response:
            return response.read() if raw else json.load(response)

    def login(self):
        self.session = None
        self.session = self.request("POST", "/v1/accounts/login", self.credentials)
        return self.session

    def logout(self):
        try:
            self.request("POST", "/v1/accounts/logout", {})
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
        self.session = None


def main():
    namespace = urllib.parse.urlsplit(os.environ["L03_IDENTITY_DATABASE_URL"]).path
    if not namespace.startswith("/bt_l03_identity_"):
        raise SystemExit("Only the generated isolated Identity namespace is allowed")
    credentials = json.loads((ARTIFACTS / "isolated-actors.key").read_text())
    operator, reviewer = Actor(credentials["operator"]), Actor(credentials["reviewer"])
    buyer = Actor({"email": os.environ["BT_DEMO_BUYER_EMAIL"], "password": os.environ["BT_DEMO_BUYER_PASSWORD"]})
    try:
        operator.login()
        reviewer.login()
        buyer.login()
        subject = buyer.session["account"]["id"]
        case = buyer.request("GET", "/v1/private-seller/applications/me")["application"]
        assert case and case["subject_id"] == subject
        review = operator.request(
            "POST",
            "/v1/private-reviews",
            {
                "application_id": case["id"],
                "reviewer_id": reviewer.session["account"]["id"],
                "reason": "Assign separate qualified reviewer for labeled synthetic proof",
            },
            key="l03-isolated-review-assignment",
        )
        detail = reviewer.request("GET", f"/v1/private-reviews/{review['id']}")
        evidence = reviewer.request("GET", f"/v1/private-reviews/{review['id']}/evidence")["items"]
        assert {item["kind"] for item in evidence} == {"identity", "possession"}
        for item in evidence:
            content = reviewer.request("GET", f"/v1/private-reviews/{review['id']}/files/{item['id']}", raw=True)
            assert content.startswith(b"DEMO:") and len(content) < 65536
        if detail["state"] != "approved":
            reviewer.request(
                "POST",
                f"/v1/private-reviews/{review['id']}/verdict",
                {
                    "revision": detail["revision"],
                    "application_revision": detail["application_revision"],
                    "state": "approved",
                    "reason": "Reviewed both synthetic proofs independently; no watch inspection is implied",
                },
                key="l03-isolated-synthetic-approval",
            )
        case = buyer.request("GET", "/v1/private-seller/applications/me")["application"]
        assert case["status"] == "approved"
        business = operator.request(
            "POST",
            "/v1/businesses",
            {
                "legal_name": "Sample Isolated Watch House SAL",
                "public_name": "Sample Isolated Watch House",
                "kind": "dealer",
                "capabilities": ["sales"],
                "assurance_reference": "SAMPLE-ISOLATED-COMMUNICATION",
                "reason": "Labeled synthetic official onboarding through the real command",
                "sample": True,
            },
            key="l03-isolated-demo-dealer",
        )
        assert business["sample"] and business["authenticated_business"]
        operator.request(
            "POST",
            "/v1/memberships",
            {
                "business_id": business["id"],
                "subject_id": subject,
                "capabilities": ["business.stock.write"],
                "qualifications": ["Synthetic stock authorization"],
                "intervention_scope": "Own sample dealer stock only",
                "reason": "Separate operator grants exact sample dealer stock permission",
            },
            key="l03-isolated-stock-membership",
        )
        buyer.login()  # Membership changes fence earlier lineages; use genuine new authority.
        assert "identity.listings.publish" in buyer.session["principal"]["permissions"]
        selected = buyer.request("GET", "/internal/v1/principal?organization_id=" + business["id"])
        assert any(
            grant["organization_id"] == business["id"] and "business.stock.write" in grant["permissions"]
            for grant in selected["organization_grants"]
        )
        environment = {
            **os.environ,
            "BT_DEMO_PRIVATE_TOKEN": buyer.session["access_token"],
            "BT_DEMO_DEALER_TOKEN": buyer.session["access_token"],
            "BT_DEMO_DEALER_ORGANIZATION_ID": business["id"],
        }
        command = [
            "docker",
            "compose",
            "-f",
            "tests/lanes/L03/compose.isolated.yaml",
            "exec",
            "-T",
            "-e",
            "BT_DEMO_PRIVATE_TOKEN",
            "-e",
            "BT_DEMO_DEALER_TOKEN",
            "-e",
            "BT_DEMO_DEALER_ORGANIZATION_ID",
            "-e",
            "BT_DEMO_IMPORT_ACK=illustrative-stock-only",
            "l03-catalog",
            "python",
            "-m",
            "bt_runtime.fixtures",
            "L03.listings",
            "demo",
        ]
        snapshots = []
        for _ in range(2):
            subprocess.run(command, env=environment, cwd=ROOT, check=True)
            personal = buyer.request("GET", "/v1/seller/listings", base=CATALOG)["items"]
            dealer = buyer.request("GET", "/v1/seller/listings?organization_id=" + business["id"], base=CATALOG)[
                "items"
            ]
            rows = [row for row in personal + dealer if row["is_demo"]]
            assert len(rows) == 6 and all(row["status"] == "published" and row["photo_ids"] for row in rows)
            snapshots.append(sorted(row["id"] for row in rows))
        assert snapshots[0] == snapshots[1]
        for listing_id in snapshots[0]:
            public = buyer.request("GET", f"/v1/listings/{listing_id}/publication", base=CATALOG)
            assert public["is_demo"] and "fee_snapshot" not in public
            credits = buyer.request("GET", f"/v1/listings/{listing_id}/photo-credits", base=CATALOG)["items"]
            assert credits and credits[0]["credit"]["author"] and credits[0]["credit"]["license_url"]
            asset = credits[0]["asset_id"]
            picture = buyer.request("GET", f"/v1/listings/{listing_id}/photos/{asset}/detail", base=CATALOG, raw=True)
            assert picture.startswith(b"\xff\xd8") and credits[0]["credit"]["license_url"].encode() in picture
        proof = {
            "sample": True,
            "subject_id": subject,
            "application_id": case["id"],
            "review_id": review["id"],
            "review_state": case["status"],
            "business_id": business["id"],
            "listing_ids": snapshots[0],
            "import_count_each_run": 6,
            "idempotent_stock": True,
            "physical_inspection": False,
            "payment": False,
            "receipt": False,
            "payout": False,
        }
        (ARTIFACTS / "connected-demo.json").write_text(json.dumps(proof, indent=2))
        print(json.dumps(proof))
    finally:
        for actor in (operator, reviewer, buyer):
            if actor.session:
                actor.logout()


if __name__ == "__main__":
    main()
