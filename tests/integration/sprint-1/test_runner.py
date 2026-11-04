import asyncio
import json
import unittest
import httpx
from runner import Runner, interpolate, check, validate_step, EvidenceError


class RunnerProof(unittest.TestCase):
    def test_contract_assertions_and_capture(self):
        self.assertEqual(
            interpolate({"id": "${capture.id}", "message": "watch-${capture.id}"}, {"capture": {"id": 3}}),
            {"id": 3, "message": "watch-3"},
        )
        check(
            {"private": False, "items": ["sample"]},
            [{"path": "private", "op": "false"}, {"path": "items", "op": "count", "value": 1}],
        )
        with self.assertRaises(AssertionError):
            check({"private": True}, [{"path": "private", "op": "false"}])

    def test_money_and_utc_assertions_reject_coercion(self):
        check(
            {"amount": 100, "at": "2026-11-04T09:00:00Z"},
            [{"path": "amount", "op": "integer"}, {"path": "at", "op": "utc"}],
        )
        for value in (True, 100.0, "100", float("inf")):
            with self.assertRaises(AssertionError):
                check({"amount": value}, [{"path": "amount", "op": "integer"}])
        for value in ("2026-11-04T09:00:00", "2026-11-04T11:00:00+02:00", "not-an-instant"):
            with self.assertRaises(AssertionError):
                check({"at": value}, [{"path": "at", "op": "utc"}])
        with self.assertRaises(AssertionError):
            check({"permission": True}, [{"path": "permission", "value": 1}])

    def test_only_real_local_origin(self):
        for origin in (
            "https://example.com",
            "http://user:password@localhost:3000",
            "file:///tmp/site",
            "http://localhost:3000?secret=x",
            "http://localhost:3000/#fragment",
        ):
            with self.assertRaises(ValueError):
                Runner(origin, {"steps": []}, {})

    def test_partial_success_cannot_claim_e05_complete(self):
        async def proof():
            runner = Runner(
                "http://localhost:3000",
                {
                    "steps": [
                        {
                            "id": "workspace-read",
                            "capability": "buyer_workspace",
                            "path": "/api/web/v1/communications/v1/buyer-workspace",
                            "assert": [{"path": "items", "op": "count", "value": 0}],
                        }
                    ]
                },
                {},
            )
            await runner.client.aclose()
            runner.client = httpx.AsyncClient(
                base_url="http://localhost:3000",
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []})),
            )
            report = await runner.execute()
            self.assertFalse(report["complete"])
            self.assertIn("exclusive_reservation", report["missing"])
            self.assertEqual(report["steps"][0]["status"], "passed")

        asyncio.run(proof())

    def test_invalid_race_contract_fails_closed(self):
        async def proof():
            candidate = {"id": "buyer", "path": "/api/web/v1/orders/v1/reservations", "method": "POST"}
            runner = Runner(
                "http://localhost:3000",
                {"steps": [{"id": "bad-race", "capability": "exclusive_reservation", "race": [candidate, candidate]}]},
                {},
            )
            await runner.client.aclose()
            runner.client = httpx.AsyncClient(
                base_url="http://localhost:3000",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json={"status": "succeeded", "order": {"state": "awaiting_payment"}}
                    )
                ),
            )
            report = await runner.execute()
            self.assertFalse(report["complete"])
            self.assertEqual(report["steps"][0]["status"], "failed")

        asyncio.run(proof())

    def test_unavailable_and_unreleased_require_actual_outcomes(self):
        for step in (
            {
                "id": "not-an-outage",
                "capability": "source_unavailable",
                "path": "/api/web/v1/orders/v1/orders",
                "assert": [{"path": "items", "op": "count", "value": 0}],
            },
            {
                "id": "not-a-denial",
                "capability": "unreleased_denied",
                "path": "/api/web/v1/orders/v1/orders",
                "status": 409,
                "assert": [{"path": "error.code", "op": "present"}],
            },
        ):
            with self.assertRaises(EvidenceError):
                validate_step(step)

    def test_actual_race_binding_and_double_winner(self):
        async def proof(double=False, foreign=False):
            candidates = [
                {
                    "id": "buyer-" + name,
                    "actor": name,
                    "operation_key": "stable-" + name,
                    "method": "POST",
                    "path": "/api/web/v1/orders/v1/reservations",
                    "body": {"watch_id": "one-physical-watch", "quote_id": "quote-" + name, "expected_revision": 1},
                }
                for name in ("one", "two")
            ]
            runner = Runner(
                "http://localhost:3000",
                {"steps": [{"id": "real-race-shape", "capability": "exclusive_reservation", "race": candidates}]},
                {name: {"email": name} for name in ("one", "two")},
            )
            await runner.client.aclose()

            def transport(request):
                if request.url.path.endswith("/login"):
                    name = json.loads(request.content)["email"]
                    return httpx.Response(
                        200, json={"access_token": name, "principal": {"actor": {"subject_id": name}}}
                    )
                name = request.headers["Authorization"].removeprefix("Bearer ")
                if name == "one" and not double:
                    return httpx.Response(
                        200, json={"status": "denied", "payment_authority": False, "code": "watch_unavailable"}
                    )
                return httpx.Response(
                    200,
                    json={
                        "status": "succeeded",
                        "order": {
                            "state": "awaiting_payment",
                            "buyer_id": "foreign" if foreign else name,
                            "watch_id": "one-physical-watch",
                            "total_minor": 100,
                            "currency": "USD",
                            "payment_authority": False,
                        },
                    },
                )

            runner.client = httpx.AsyncClient(
                base_url="http://localhost:3000", transport=httpx.MockTransport(transport)
            )
            report = await runner.execute()
            self.assertFalse(report["complete"])
            self.assertEqual(report["steps"][0]["status"], "failed" if double or foreign else "passed")

        asyncio.run(proof())
        asyncio.run(proof(double=True))
        asyncio.run(proof(foreign=True))

    def test_expired_actor_reauthenticates_once_with_same_key(self):
        async def proof():
            step = {
                "id": "save-draft",
                "capability": "private_draft",
                "actor": "buyer",
                "method": "POST",
                "operation_key": "stable-draft",
                "path": "/api/web/v1/catalog/v1/request-drafts",
                "body": {},
                "assert": [{"path": "status", "value": "succeeded"}],
            }
            runner = Runner("http://localhost:3000", {"steps": [step]}, {"buyer": {"email": "buyer"}})
            await runner.client.aclose()
            logins = []
            writes = []

            def transport(request):
                if request.url.path.endswith("/login"):
                    logins.append(True)
                    return httpx.Response(
                        200, json={"access_token": str(len(logins)), "principal": {"actor": {"subject_id": "buyer"}}}
                    )
                writes.append(request.headers["Idempotency-Key"])
                return httpx.Response(401 if len(writes) == 1 else 200, json={"status": "succeeded"})

            runner.client = httpx.AsyncClient(
                base_url="http://localhost:3000", transport=httpx.MockTransport(transport)
            )
            report = await runner.execute()
            self.assertEqual(report["steps"][0]["status"], "passed")
            self.assertEqual(len(logins), 2)
            self.assertEqual(writes, ["stable-draft", "stable-draft"])

        asyncio.run(proof())

    def test_login_outage_is_an_incomplete_safe_report(self):
        async def proof():
            runner = Runner(
                "http://localhost:3000",
                {"steps": []},
                {"buyer": {"email": "not-logged@example.test", "password": "never-emitted"}},
            )
            await runner.client.aclose()
            runner.client = httpx.AsyncClient(
                base_url="http://localhost:3000",
                transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"private": "must-not-emit"})),
            )
            report = await runner.execute()
            self.assertFalse(report["complete"])
            self.assertEqual(report["steps"][0]["code"], "authentication_or_input_unavailable")
            self.assertNotIn("never-emitted", json.dumps(report))
            self.assertNotIn("must-not-emit", json.dumps(report))

        asyncio.run(proof())

    def test_missing_list_item_records_safe_failure(self):
        async def proof():
            runner = Runner(
                "http://localhost:3000",
                {
                    "steps": [
                        {
                            "id": "missing-item",
                            "capability": "buyer_workspace",
                            "path": "/api/web/v1/communications/v1/buyer-workspace",
                            "assert": [{"path": "items.0.id", "op": "present"}],
                        }
                    ]
                },
                {},
            )
            await runner.client.aclose()
            runner.client = httpx.AsyncClient(
                base_url="http://localhost:3000",
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []})),
            )
            report = await runner.execute()
            self.assertEqual(report["steps"][0]["code"], "transport_or_contract_failed")

        asyncio.run(proof())


if __name__ == "__main__":
    unittest.main()
