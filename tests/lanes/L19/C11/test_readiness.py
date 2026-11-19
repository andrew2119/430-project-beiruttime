import asyncio
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "capacity_readiness", ROOT / "services/eligibility/modules/capacity/readiness.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
FIXTURES = json.loads((ROOT / "packages/contracts-eligibility/capacity/fixtures.json").read_text())


class Source:
    authority = True
    unavailable = False

    def __init__(self, payment):
        self.payment = payment
        self.support = MODULE.Support(**FIXTURES["support"])

    async def current_authority(self, context):
        return self.authority

    async def orders_payment(self, context):
        if self.unavailable:
            raise TimeoutError
        return self.payment


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = MODULE.Context(**FIXTURES["context"])
        self.payment = MODULE.Payment(**FIXTURES["payment"])

    async def test_contract_cases(self):
        for case in FIXTURES["cases"]:
            with self.subTest(case=case["name"]):
                source = Source(replace(self.payment, **case["changes"]))
                source.unavailable = case.get("unavailable", False)
                result = await MODULE.read(self.context, source)
                self.assertEqual(result["state"], case["expected"])
                self.assertFalse(result["identity_pass"])
                self.assertFalse(result["execution_authorized"])
                self.assertTrue(result["message"]["en"])
                self.assertTrue(result["message"]["ar"])

    async def test_every_binding(self):
        for key, value in FIXTURES["payment"].items():
            if key in {"state", "payment_operation_id"}:
                continue
            wrong = value + 1 if type(value) is int else "other"
            with self.subTest(binding=key):
                result = await MODULE.read(self.context, Source(replace(self.payment, **{key: wrong})))
                self.assertEqual(result["state"], "denied")

    async def test_retry_rechecks_revocation(self):
        source = Source(self.payment)
        first = await MODULE.read(self.context, source)
        self.assertEqual(first, await MODULE.read(self.context, source))
        source.authority = False
        self.assertEqual((await MODULE.read(self.context, source))["state"], "denied")
        source.authority = None
        self.assertEqual((await MODULE.read(self.context, source))["state"], "pending")

    async def test_same_reference_changed_binding_rechecks(self):
        source = Source(self.payment)
        self.assertEqual((await MODULE.read(self.context, source))["state"], "paid")
        changed = replace(self.context, quote_id="other")
        self.assertEqual((await MODULE.read(changed, source))["state"], "denied")

    async def test_lost_response_recovers_same_reference(self):
        source = Source(None)
        self.assertEqual((await MODULE.read(self.context, source))["state"], "pending")
        source.payment = self.payment
        result = await MODULE.read(self.context, source)
        self.assertEqual(result["state"], "paid")
        self.assertEqual(result["operation_id"], self.context.operation_id)

    async def test_bounded_source(self):
        class Slow(Source):
            async def current_authority(self, context):
                await asyncio.sleep(2)

        result = await MODULE.read(self.context, Slow(self.payment))
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["next_actor"], "synthetic-support-operator")
        self.assertEqual(result["next_review_at"], "2026-11-17T10:00:00+00:00")

    async def test_invalid_context(self):
        for changes in ({"total_minor": True}, {"currency": "other"}, {"order_kind": "sale"}, {"subject_id": "other"}):
            self.assertEqual((await MODULE.read(replace(self.context, **changes), Source(self.payment)))["state"], "denied")

    async def test_malformed_source_is_pending(self):
        for payment in ({}, replace(self.payment, state=[]), replace(self.payment, payment_operation_id=True)):
            self.assertEqual((await MODULE.read(self.context, Source(payment)))["state"], "pending")

    async def test_contract_schemas(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Schema validator dependency is unavailable.")

        folder = ROOT / "packages/contracts-eligibility/capacity"
        for filename, value in (
            ("context.schema.json", FIXTURES["context"]),
            ("payment.schema.json", FIXTURES["payment"]),
            ("result.schema.json", await MODULE.read(self.context, Source(self.payment))),
            ("result.schema.json", await MODULE.read(replace(self.context, currency="other"), Source(self.payment))),
            ("result.schema.json", await MODULE.read(replace(self.context, total_minor=True), Source(self.payment))),
            ("result.schema.json", await MODULE.read(replace(self.context, request_revision=0), Source(self.payment))),
            ("result.schema.json", await MODULE.read(replace(self.context, payment_revision=0), Source(self.payment))),
            ("result.schema.json", await MODULE.read(replace(self.context, actor_id=None), Source(self.payment))),
        ):
            schema = json.loads((folder / filename).read_text())
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(value, schema)


    async def test_pending_support_survives_retries_and_restart(self):
        for authority, unavailable, payment in (
            (None, False, self.payment),
            (True, True, self.payment),
            (True, False, None),
            (True, False, {}),
            (True, False, replace(self.payment, state="unknown")),
        ):
            with self.subTest(authority=authority, unavailable=unavailable, payment=payment):
                source = Source(payment)
                source.authority = authority
                source.unavailable = unavailable
                first = await MODULE.read(self.context, source)
                second = await MODULE.read(self.context, source)
                restarted = Source(payment)
                restarted.authority = authority
                restarted.unavailable = unavailable
                third = await MODULE.read(self.context, restarted)
                self.assertEqual(first, second)
                self.assertEqual(first, third)
                self.assertEqual(first["state"], "pending")
                self.assertEqual(first["next_actor"], "synthetic-support-operator")
                self.assertNotEqual(first["next_actor"], self.context.actor_id)
                self.assertEqual(first["next_review_at"], "2026-11-17T10:00:00+00:00")
                self.assertEqual(first["escalate_at"], "2026-11-18T10:00:00+00:00")
                self.assertTrue(first["next_action"]["en"])
                self.assertTrue(first["next_action"]["ar"])

    async def test_recorded_progress_and_reassignment_keep_first_deadline(self):
        source = Source(None)
        source.support = replace(source.support, operator_id="synthetic-replacement",
                                 last_progress_at="2026-11-17T09:00:00+00:00")
        result = await MODULE.read(self.context, source)
        self.assertEqual(result["next_actor"], "synthetic-replacement")
        self.assertEqual(result["next_review_at"], "2026-11-17T10:00:00+00:00")
        self.assertEqual(result["escalate_at"], "2026-11-19T09:00:00+00:00")

    async def test_invalid_support_cannot_return_unassigned_pending(self):
        for changes in ({"operator_id": " "}, {"operation_id": "other"},
                        {"opened_at": "2026-11-16T10:00:00"},
                        {"last_progress_at": "2026-11-15T10:00:00+00:00"}):
            source = Source(None)
            source.support = replace(source.support, **changes)
            with self.assertRaises(ValueError):
                await MODULE.read(self.context, source)

    async def test_pending_schema_requires_support_deadlines(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Schema validator dependency is unavailable.")

        folder = ROOT / "packages/contracts-eligibility/capacity"
        schema = json.loads((folder / "result.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        result = await MODULE.read(self.context, Source(None))
        validator.validate(result)
        for key, value in (("next_actor", ""), ("next_review_at", None),
                           ("escalate_at", None), ("escalate_at", "invalid")):
            with self.subTest(key=key, value=value), self.assertRaises(jsonschema.ValidationError):
                validator.validate({**result, key: value})
        support_schema = json.loads((folder / "support.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(support_schema)
        jsonschema.validate(FIXTURES["support"], support_schema,
                            format_checker=jsonschema.FormatChecker())
