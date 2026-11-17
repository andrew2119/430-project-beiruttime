"""Pure lifecycle contract checks with no external side effects."""

import copy
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "native_lifecycle", Path(__file__).resolve().parents[3] / "scripts/native-lifecycle.py")
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


class Stub:
    def __init__(self):
        self.record = {"schema_version": driver.SCHEMA, "pid": 101,
                       "start_time": "one", "run_dir": "/tmp/n06",
                       "run_id": "owned", "owned_replica": True,
                       "runtime_kind": "owning", "domain": "communications",
                       "url": "http://127.0.0.1:19008",
                       "database": {"id": "disposable", "disposable": True,
                                    "restricted": True, "run_id": "owned"}}
        self.events = []
        self.failure = None
        self.disrupted = False
        self.restored_states = []
        self.cleaned = False
        self.domain_statuses = {
            domain: ("unavailable" if domain == "communications" else "ready")
            for domain in ("identity", "eligibility", "catalog", "auction", "pricing",
                           "communications", "orders", "trust", "service-operations")}
        self.bad_retry = False
        self.changed = False
        self.observation_count = 0
        self.foreign_observation = None
        self.cleanup_calls = []
        self.deliveries = 1
        self.duplicates = 0
        self.replay_enabled = True
        self.replay_override = {}

    def start(self, proof, run_dir, timeout):
        self.events.append("start")
        return copy.deepcopy(self.record)

    def observe(self, record, timeout):
        self.observation_count += 1
        result = copy.deepcopy(self.record)
        if self.changed:
            result.update(pid=102, start_time="two")
        if self.foreign_observation is not None:
            observation, key, value = self.foreign_observation
            if self.observation_count == observation:
                result[key] = value
        return result

    def operation(self, record, timeout):
        return dict(operation_id="op", subject_id="subject", durable_reference="row",
                    state_digest="retained", effect_count=1, outbox_reference="event",
                    inbox_reference="delivery", outbox_pending=0, inbox_effect_count=1)

    def disrupt(self, record, proof, timeout):
        self.events.append("disrupt")
        self.disrupted = True
        self.changed = proof in {"process-restart", "replay"}
        if self.failure:
            raise self.failure

    def isolation(self, record, timeout):
        return dict(shell_available=True, catalog_available=True,
                    unavailable_domains=["communications"],
                    domain_statuses=self.domain_statuses, dependency_status=503,
                    error_code="unavailable", request_id_present=True)

    def restore(self, record, proof, timeout):
        self.restored_states.append(self.disrupted)
        self.disrupted = False
        self.events.append("restore")

    def recovered(self, record, timeout):
        self.events.append("recovered")

    def retry(self, record, operation_id, timeout):
        self.events.append(operation_id)
        if self.replay_enabled:
            self.deliveries += 1
            self.duplicates += 1
        return {"healthy": True} if self.bad_retry else self.operation(record, timeout)

    def replay_evidence(self, record, operation_id, timeout):
        self.events.append("replay-observation")
        result = dict(operation_id=operation_id, outbox_reference="event",
                      inbox_reference="delivery", run_id="owned", database_id="disposable",
                      outbox_delivery_count=self.deliveries,
                      inbox_delivery_count=self.deliveries,
                      inbox_duplicate_count=self.duplicates)
        if self.deliveries > 1:
            result.update(self.replay_override)
        return result

    def database_restart_evidence(self, record, timeout):
        return dict(database_id="disposable", before_start_time="one", after_start_time="two")

    def cleanup(self, run_dir, timeout):
        self.cleaned = True
        self.cleanup_calls.append((run_dir, timeout))
        self.events.append("cleanup")


class LifecycleTests(unittest.TestCase):
    def test_plan_keeps_unverified_acceptance_checks_deferred(self):
        result = driver.plan()
        self.assertEqual(result["state"], "deferred")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["acceptance_checks"], {
            "original_mapping_comparison": "deferred",
            "recursive_lease_overlap": "deferred"})

    def test_all_proofs(self):
        for proof in driver.PROOFS:
            with self.subTest(proof=proof):
                stub = Stub()
                self.assertEqual(driver.exercise(stub, proof, "/tmp/n06")["state"], "passed")
                self.assertEqual(stub.events[-1], "cleanup")
                self.assertIn("restore", stub.events)
                self.assertIn("op", stub.events)

    def test_unknown_domain_refused_before_operation_or_disruption(self):
        for proof in driver.PROOFS:
            with self.subTest(proof=proof):
                stub = Stub()
                stub.record["domain"] = "unknown"
                stub.domain_statuses = dict.fromkeys(driver.DOMAINS, "ready")

                def unexpected_operation(*args, **kwargs):
                    self.fail("Unknown domain reached operation")

                stub.operation = unexpected_operation
                with self.assertRaisesRegex(driver.Refused, "Unknown domain"):
                    driver.exercise(stub, proof, "/tmp/n06")
                self.assertEqual(stub.events, ["start", "cleanup"])
                self.assertEqual(stub.cleanup_calls, [("/tmp/n06", 30)])

    def test_foreign_identity_refused(self):
        for key, value in (("pid", 999), ("start_time", "foreign"),
                           ("run_dir", "/tmp/foreign")):
            with self.subTest(key=key):
                stub = Stub()
                original = copy.deepcopy(stub.record)
                stub.record[key] = value
                with self.assertRaises(driver.Refused):
                    driver.same_process(original, stub.record, "/tmp/n06")
                self.assertEqual(stub.events, [])

    def test_foreign_observation_refused_before_disruption(self):
        for proof in driver.PROOFS:
            for observation in (1, 2):
                for key, value in (("pid", 999), ("start_time", "foreign"),
                                   ("run_dir", "/tmp/foreign")):
                    with self.subTest(proof=proof, observation=observation, key=key):
                        stub = Stub()
                        original = copy.deepcopy(stub.record)
                        stub.foreign_observation = (observation, key, value)
                        with self.assertRaises(driver.Refused):
                            driver.exercise(stub, proof, "/tmp/n06")
                        self.assertEqual(stub.observation_count, observation)
                        self.assertNotIn("disrupt", stub.events)
                        self.assertNotIn("recovered", stub.events)
                        self.assertNotIn("op", stub.events)
                        self.assertEqual(stub.record, original)
                        self.assertEqual(stub.cleanup_calls, [("/tmp/n06", 30)])
                        self.assertEqual(stub.events[-1], "cleanup")
                        self.assertEqual(stub.events.count("restore"), observation - 1)

    def test_restore_on_failure_and_interruption(self):
        for proof in driver.PROOFS:
            for failure in (RuntimeError("failure"), KeyboardInterrupt()):
                with self.subTest(proof=proof, failure=type(failure).__name__):
                    stub = Stub()
                    stub.failure = failure
                    with self.assertRaises(type(failure)) as raised:
                        driver.exercise(stub, proof, "/tmp/n06")
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(stub.restored_states, [True])
                    self.assertFalse(stub.disrupted)
                    self.assertTrue(stub.cleaned)
                    self.assertEqual(stub.cleanup_calls, [("/tmp/n06", 30)])
                    self.assertEqual(stub.events[-2:], ["restore", "cleanup"])

    def test_outage_requires_complete_domain_status_response(self):
        for domain in tuple(Stub().domain_statuses):
            with self.subTest(missing=domain):
                stub = Stub()
                del stub.domain_statuses[domain]
                with self.assertRaises(driver.Refused):
                    driver.exercise(stub, "dependency-outage", "/tmp/n06")
                self.assertEqual(stub.restored_states, [True])
                self.assertFalse(stub.disrupted)
                self.assertTrue(stub.cleaned)

    def test_outage_refuses_extra_or_unaffected_unready_domain(self):
        for domain, status in (("foreign", "ready"), ("catalog", "unavailable")):
            with self.subTest(domain=domain):
                stub = Stub()
                stub.domain_statuses[domain] = status
                with self.assertRaises(driver.Refused):
                    driver.exercise(stub, "dependency-outage", "/tmp/n06")
                self.assertFalse(stub.disrupted)
                self.assertTrue(stub.cleaned)

    def test_health_only_refused_after_restart(self):
        stub = Stub()
        stub.bad_retry = True
        with self.assertRaises(driver.Refused):
            driver.exercise(stub, "replay", "/tmp/n06")
        self.assertTrue(stub.changed)
        self.assertEqual(stub.events[-1], "cleanup")

    def test_no_process_restart_refused(self):
        stub = Stub()
        stub.disrupt = lambda *args, **kwargs: None
        with self.assertRaises(driver.Refused):
            driver.exercise(stub, "process-restart", "/tmp/n06")

    def test_replay_retention_and_deduplication(self):
        before = Stub().operation(None, 10)
        for key in before:
            after = before.copy()
            after[key] = 2 if isinstance(before[key], int) else "changed"
            with self.subTest(key=key), self.assertRaises(driver.Refused):
                driver.retained(before, after)

    def test_unchanged_converged_operation_is_not_replay(self):
        stub = Stub()
        stub.replay_enabled = False
        with self.assertRaises(driver.Refused):
            driver.exercise(stub, "replay", "/tmp/n06")
        self.assertEqual(stub.events[-1], "cleanup")

    def test_replay_requires_each_attributable_counter(self):
        changes = {"operation_id": "other", "outbox_reference": "other",
                   "inbox_reference": "other", "run_id": "other", "database_id": "other",
                   "outbox_delivery_count": 1, "inbox_delivery_count": 1,
                   "inbox_duplicate_count": 0}
        for key, value in changes.items():
            with self.subTest(key=key):
                stub = Stub()
                stub.replay_override[key] = value
                with self.assertRaises(driver.Refused):
                    driver.exercise(stub, "replay", "/tmp/n06")
                self.assertEqual(stub.events[-1], "cleanup")

    def test_invalid_replay_counters_refused(self):
        for value in (None, True, -1, "2"):
            stub = Stub()
            stub.replay_override["inbox_duplicate_count"] = value
            with self.subTest(value=value), self.assertRaises(driver.Refused):
                driver.exercise(stub, "replay", "/tmp/n06")

    def test_shared_storage_and_nonloopback_refused(self):
        for key, value in (("owned_replica", False), ("url", "http://example.invalid:80")):
            stub = Stub()
            stub.record[key] = value
            with self.assertRaises(driver.Refused):
                driver.exercise(stub, "replay", "/tmp/n06")
            self.assertNotIn("disrupt", stub.events)
            self.assertEqual(stub.events[-1], "cleanup")

    def test_fallback_guard(self):
        record = Stub().record
        record.update(runtime_kind="foundation-fallback", image="foreign")
        with self.assertRaises(driver.Refused):
            driver.validate(record, "/tmp/n06")


if __name__ == "__main__":
    unittest.main()
