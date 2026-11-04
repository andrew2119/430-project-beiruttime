"""Run explicit, real local HTTP scenarios and emit privacy-safe acceptance evidence.

No runtime stubs, direct SQL repairs, shell execution, service lifecycle or fabricated
business outcomes. Supplier fixture commands create sample content through their APIs.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
import httpx

REQUIRED = {
    "private_publication",
    "dealer_publication",
    "browse_search_detail",
    "manual_bid",
    "private_maximum",
    "live_projection",
    "exclusive_reservation",
    "seller_moderation",
    "official_directory",
    "business_options",
    "technical_intake",
    "private_consent",
    "buyer_workspace",
    "seller_workspace",
    "purchase_readiness",
    "private_draft",
    "operator_workspace",
    "source_unavailable",
    "second_seller_denied",
    "unreleased_denied",
}
PLACEHOLDER = re.compile(r"\$\{([A-Za-z0-9_.-]+)\}")
CAPABILITY_SERVICES = {
    "private_publication": {"catalog"},
    "dealer_publication": {"catalog"},
    "browse_search_detail": {"catalog"},
    "manual_bid": {"auction"},
    "private_maximum": {"auction"},
    "live_projection": {"auction"},
    "exclusive_reservation": {"orders"},
    "seller_moderation": {"trust"},
    "official_directory": {"service-operations"},
    "business_options": {"catalog"},
    "technical_intake": {"service-operations"},
    "private_consent": {"eligibility"},
    "buyer_workspace": {"communications"},
    "seller_workspace": {"communications"},
    "purchase_readiness": {"communications"},
    "private_draft": {"catalog"},
    "operator_workspace": {"communications", "trust"},
}
MUTATIONS = {
    "private_publication",
    "dealer_publication",
    "manual_bid",
    "private_maximum",
    "seller_moderation",
    "technical_intake",
    "private_consent",
    "private_draft",
}


class EvidenceError(Exception):
    def __init__(self, code, status=None, request_id=""):
        self.code, self.status, self.request_id = code, status, request_id


def validate_step(step):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", step.get("id", "")) or step.get("capability") not in REQUIRED:
        raise EvidenceError("invalid_step_contract")
    if step.get("race"):
        candidates = step["race"]
        if step["capability"] != "exclusive_reservation" or len(candidates) != 2:
            raise EvidenceError("invalid_race_contract")
        if any(
            s.get("method") != "POST"
            or s.get("path") != "/api/web/v1/orders/v1/reservations"
            or not s.get("actor")
            or not s.get("operation_key")
            or not s.get("body", {}).get("watch_id")
            for s in candidates
        ):
            raise EvidenceError("invalid_race_contract")
        if (
            candidates[0]["actor"] == candidates[1]["actor"]
            or candidates[0]["operation_key"] == candidates[1]["operation_key"]
        ):
            raise EvidenceError("race_requires_distinct_buyers_and_keys")
        return
    if step["capability"] == "exclusive_reservation" or not step.get("assert"):
        raise EvidenceError("missing_acceptance_assertions")
    path = step.get("path", "")
    if not re.match(r"^/api/(web|mobile)/v1/[a-z-]+/v1/", path) or "/health" in path or "/status" in path:
        raise EvidenceError("not_a_domain_acceptance_operation")
    allowed = CAPABILITY_SERVICES.get(step["capability"])
    if allowed and path.split("/")[4] not in allowed:
        raise EvidenceError("wrong_capability_service")
    if step["capability"] in MUTATIONS and step.get("method", "GET") not in ("POST", "PATCH", "PUT", "DELETE"):
        raise EvidenceError("capability_requires_real_mutation")
    if step["capability"] not in {"source_unavailable", "second_seller_denied", "unreleased_denied"} and step.get(
        "status", 200
    ) not in (200, 201):
        raise EvidenceError("positive_capability_requires_acknowledgement")
    if step["capability"] in MUTATIONS and not step.get("operation_key"):
        raise EvidenceError("mutation_requires_stable_operation_key")
    if step["capability"] in {"manual_bid", "private_maximum", "private_draft"} and not any(
        item.get("path") == "status" and item.get("op", "eq") == "eq" and item.get("value") == "succeeded"
        for item in step["assert"]
    ):
        raise EvidenceError("missing_successful_domain_outcome")
    if step["capability"] == "second_seller_denied" and step.get("status") not in (403, 404):
        raise EvidenceError("second_seller_must_be_denied")
    if step["capability"] == "unreleased_denied" and (
        step.get("status") not in (403, 404, 409) or step.get("method", "GET") not in ("POST", "PATCH", "PUT", "DELETE")
    ):
        raise EvidenceError("unreleased_capability_must_be_denied")
    if step["capability"] == "source_unavailable" and step.get("status", 200) not in (502, 503, 504):
        if not any(item.get("op", "eq") == "eq" and item.get("value") == "unavailable" for item in step["assert"]):
            raise EvidenceError("missing_actual_unavailable_assertion")


def at(value, path):
    for part in path.split(".") if path else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def interpolate(value, context):
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, context) for v in value]
    if not isinstance(value, str):
        return value
    match = PLACEHOLDER.fullmatch(value)
    if match:
        return at(context, match[1])
    return PLACEHOLDER.sub(lambda m: str(at(context, m[1])), value)


def exact_json(value, expected):
    return json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def utc_instant(value):
    try:
        instant = datetime.fromisoformat(value)
        return instant.utcoffset() is not None and instant.utcoffset().total_seconds() == 0
    except (ValueError, TypeError):
        return False


def check(body, assertions):
    for assertion in assertions:
        value = at(body, assertion["path"])
        operation = assertion.get("op", "eq")
        expected = assertion.get("value")
        valid = {
            "eq": lambda: exact_json(value, expected),
            "ne": lambda: not exact_json(value, expected),
            "integer": lambda: type(value) is int and -9000000000000000 <= value <= 9000000000000000,
            "utc": lambda: utc_instant(value),
            "contains": lambda: expected in value,
            "count": lambda: len(value) == expected,
            "gte": lambda: value >= expected,
            "lte": lambda: value <= expected,
            "present": lambda: value is not None,
            "false": lambda: value is False,
        }.get(operation)
        if not valid or not valid():
            raise AssertionError("Response contract assertion failed")


class Runner:
    def __init__(self, origin, scenario, credentials):
        parsed = urlparse(origin)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Integration origin must be a local application origin")
        self.client = httpx.AsyncClient(
            base_url=origin,
            timeout=httpx.Timeout(5, connect=0.5),
            limits=httpx.Limits(max_connections=8),
            follow_redirects=False,
        )
        self.scenario = scenario
        self.context = {"fixtures": scenario.get("fixtures", {}), "actors": {}}
        self.credentials = credentials
        self.evidence = []
        self.login_locks = {name: asyncio.Lock() for name in credentials}

    async def login_actor(self, name):
        response = await self.client.post(
            "/api/web/v1/identity/v1/accounts/login",
            json=self.credentials[name],
            headers={"Origin": str(self.client.base_url).rstrip("/")},
        )
        if response.status_code != 200:
            raise EvidenceError("real_actor_login_failed", response.status_code)
        payload = response.json()
        actor = {"token": payload["access_token"], "id": payload["principal"]["actor"]["subject_id"]}
        previous = self.context["actors"].get(name)
        if previous and previous["id"] != actor["id"]:
            raise EvidenceError("actor_changed_during_retry")
        self.context["actors"][name] = actor

    async def login(self):
        for name in self.credentials:
            await self.login_actor(name)

    async def invoke(self, step):
        path = interpolate(step["path"], self.context)
        if (
            not isinstance(path, str)
            or not path.startswith("/api/")
            or ".." in path
            or "://" in path
            or path.startswith("//")
        ):
            raise ValueError("Scenario request must use the local allowlisted gateway")
        headers = {"Origin": str(self.client.base_url).rstrip("/"), "X-Request-ID": "sprint1-" + step["id"]}
        if actor := step.get("actor"):
            headers["Authorization"] = "Bearer " + self.context["actors"][actor]["token"]
        if key := step.get("operation_key"):
            headers["Idempotency-Key"] = interpolate(key, self.context)
        options = {}
        if "upload" in step:
            upload = interpolate(step["upload"], self.context)
            repo = Path(__file__).resolve().parents[3]
            asset = (repo / upload["path"]).resolve()
            if (
                not asset.is_relative_to((repo / "web/public/demo/watches").resolve())
                or not asset.is_file()
                or asset.stat().st_size > 16 * 1024 * 1024
            ):
                raise EvidenceError("upload_must_be_bounded_demo_asset")
            options["files"] = {
                upload.get("field", "file"): (
                    asset.name,
                    asset.read_bytes(),
                    upload.get("content_type", "application/octet-stream"),
                )
            }
            if "body" in step:
                options["data"] = interpolate(step["body"], self.context)
        elif "body" in step:
            options["json"] = interpolate(step["body"], self.context)
        response = await self.client.request(step.get("method", "GET"), path, headers=headers, **options)
        if response.status_code == 401 and actor and step.get("status", 200) != 401:
            # Each actor keeps its own credential and stable command key; never refresh a shared cookie jar.
            previous = headers["Authorization"]
            async with self.login_locks[actor]:
                if "Bearer " + self.context["actors"][actor]["token"] == previous:
                    await self.login_actor(actor)
            headers["Authorization"] = "Bearer " + self.context["actors"][actor]["token"]
            response = await self.client.request(step.get("method", "GET"), path, headers=headers, **options)
        if response.status_code != step.get("status", 200):
            raise EvidenceError(
                "unexpected_http_status", response.status_code, response.headers.get("X-Request-ID", "")
            )
        payload = response.json()
        check(payload, interpolate(step.get("assert", []), self.context))
        return payload, response.headers.get("X-Request-ID", "")

    def report(self):
        covered = {e["capability"] for e in self.evidence if e["status"] == "passed"}
        missing = sorted(REQUIRED - covered)
        return {
            "schema": "sprint1-evidence.v1",
            "actual_http": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "complete": not missing and all(e["status"] == "passed" for e in self.evidence),
            "missing": missing,
            "steps": self.evidence,
        }

    async def execute(self):
        try:
            try:
                await self.login()
                if not isinstance(self.scenario.get("steps"), list) or len(self.scenario["steps"]) > 500:
                    raise EvidenceError("scenario_step_budget")
            except (EvidenceError, KeyError, ValueError, TypeError, httpx.HTTPError):
                self.evidence.append(
                    {
                        "id": "authentication-or-input",
                        "capability": "precondition",
                        "status": "failed",
                        "at": datetime.now(timezone.utc).isoformat(),
                        "code": "authentication_or_input_unavailable",
                    }
                )
                return self.report()
            for step in self.scenario["steps"]:
                started = datetime.now(timezone.utc).isoformat()
                try:
                    validate_step(step)
                    if step.get("race"):
                        candidates = step["race"]
                        if (
                            self.context["actors"][candidates[0]["actor"]]["id"]
                            == self.context["actors"][candidates[1]["actor"]]["id"]
                        ):
                            raise EvidenceError("race_requires_distinct_principals")
                        first, second = [interpolate(candidate["body"], self.context) for candidate in candidates]
                        if first["watch_id"] != second["watch_id"]:
                            raise EvidenceError("race_requires_one_physical_watch")
                        outcomes = await asyncio.gather(*(self.invoke(candidate) for candidate in candidates))
                        payloads = [value[0] for value in outcomes]
                        if sorted(value.get("status") for value in payloads) != ["denied", "succeeded"]:
                            raise AssertionError("Race did not yield exactly one reservation")
                        winner = next(v for v in payloads if v["status"] == "succeeded")
                        loser = next(v for v in payloads if v["status"] == "denied")
                        winner_index = next(
                            index for index, value in enumerate(payloads) if value["status"] == "succeeded"
                        )
                        expected_buyer = self.context["actors"][candidates[winner_index]["actor"]]["id"]
                        order = winner["order"]
                        if (
                            loser.get("payment_authority") is not False
                            or order["state"] != "awaiting_payment"
                            or order.get("payment_authority") is not False
                            or order.get("watch_id") != first["watch_id"]
                            or order.get("buyer_id") != expected_buyer
                            or (
                                "quote_id" in order
                                and order["quote_id"] != [first, second][winner_index].get("quote_id")
                            )
                            or type(order.get("total_minor")) is not int
                            or not 0 <= order["total_minor"] <= 9000000000000000
                            or order.get("currency") not in ("USD", "LBP")
                            or loser.get("code") != "watch_unavailable"
                        ):
                            raise AssertionError("Race granted invalid authority")
                        payload = {"winner": winner, "loser": loser}
                        reference = ""
                    else:
                        payload, reference = await self.invoke(step)
                    for name, path in step.get("capture", {}).items():
                        self.context[name] = at(payload, path)
                    self.evidence.append(
                        {
                            "id": step["id"],
                            "capability": step["capability"],
                            "status": "passed",
                            "at": started,
                            "request_id": reference,
                        }
                    )
                except (
                    EvidenceError,
                    AssertionError,
                    KeyError,
                    IndexError,
                    AttributeError,
                    ValueError,
                    TypeError,
                    httpx.HTTPError,
                ) as error:
                    failure = (
                        {"code": error.code, "http_status": error.status, "request_id": error.request_id}
                        if isinstance(error, EvidenceError)
                        else {"code": "transport_or_contract_failed"}
                    )
                    self.evidence.append(
                        {
                            "id": step.get("id", "invalid"),
                            "capability": step.get("capability", "invalid"),
                            "status": "failed",
                            "at": started,
                            **failure,
                        }
                    )
                    break
            return self.report()
        finally:
            await self.client.aclose()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--origin", default="http://127.0.0.1:3000")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    # Secrets enter only memory, never the scenario/evidence or terminal output.
    credentials = json.loads(os.environ["BT_SPRINT1_CREDENTIALS"])
    report = await Runner(args.origin, json.loads(args.scenario.read_text()), credentials).execute()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "passed": sum(e["status"] == "passed" for e in report["steps"]),
                "missing": report["missing"],
            }
        )
    )
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
