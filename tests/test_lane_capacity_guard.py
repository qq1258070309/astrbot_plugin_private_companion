"""Regressions for the two host-side defects that stranded proactive delivery.

1. `BackgroundCoordinator.advance()` sized its batch by its own workers only, so a
   delivery started while a judge held the single background slot was refused by
   `claim_task()` (`task_lane_full`) and the exact runner retired the queued task as
   `cancelled`/`owner_unavailable`, leaving the page stuck on 待检查 forever.
2. `ProactiveContacts.validate_judge()` required `decision == "judge_pending"`, so a
   judge that wrote its own `send`/`skip` verdict could not re-validate it in
   `finish()`: the attempt became `uncertain`/`permission_changed` after a real send.
"""

import asyncio
from datetime import timedelta
import unittest

from companion_v2.execution.models import Lane, TaskResult, TaskSpec, stamp
from companion_v2.host.background import BackgroundCoordinator
from companion_v2.proactive.service import JUDGE_KIND, ProactiveContacts
from tests.test_execution import ExecutionFixture
from tests.test_management_access import INSTALLATION


class _DeliveryQueue:
    """The coordinator-facing surface of `DeliveryService` without a platform.

    `advance()` only reads `registrations`, `settle()`, `pending()` and
    `next_wake()`, and reports refusals through `cancel_unstarted()`, so the
    double mirrors exactly those four methods plus the asynchronous `deliver`
    handler the exact runner invokes.
    """

    def __init__(self, tasks, registration, pending=()):
        self.tasks = tasks
        self.registrations = (registration,)
        self._pending = list(pending)
        self.delivered, self.cancelled = [], []

    def pending(self, *, limit, excluded=()):
        ready = [(context, task_id) for context, task_id in self._pending
                 if task_id not in excluded and self.tasks.read(context, task_id).unwrap().state == "created"]
        return tuple(ready[:limit])

    def next_wake(self, *, excluded=()):
        return None

    def cancel_unstarted(self, task_id, *, reason):
        self.cancelled.append((task_id, reason))

    def settle(self, *, limit=32):
        return 0

    async def deliver(self, run):
        self.delivered.append(run.task.task_id)
        return TaskResult("succeeded")


class _Configuration:
    """`ProactiveContacts` only reads `configuration.runtime` before `attach()`."""

    def __init__(self, runtime):
        self.runtime = runtime


class LaneCapacityGuardTests(ExecutionFixture, unittest.IsolatedAsyncioTestCase):
    """A delivery must never start on a slot another background attempt holds."""

    def setUp(self):
        super().setUp()
        self.delivery = _DeliveryQueue(self.tasks, self.tasks.registrations["fixture.background"],
                                       ((self.context, "delivery-1"),))
        self.coordinator = BackgroundCoordinator(self.tasks, self.delivery, (), notify=lambda: None)
        self.addAsyncCleanup(self.coordinator.close)

    def hold_background_slot(self):
        """A judge/compose attempt owns the only background slot (the production race)."""
        self.submit("judge-holder", kind="fixture.background")
        holder = self.tasks.claim(Lane.BACKGROUND).unwrap().claim
        self.assertIsNotNone(holder)
        self.tasks.begin(holder).unwrap()
        self.assertEqual(self.tasks.limits.background_slots, 1)
        self.assertEqual(self.tasks.held(Lane.BACKGROUND).unwrap(), 1)
        return holder

    async def test_advance_leaves_the_delivery_queued_while_another_attempt_holds_the_slot(self):
        holder = self.hold_background_slot()
        self.submit("delivery-1", kind="fixture.background")
        self.assertEqual(self.delivery.pending(limit=4), ((self.context, "delivery-1"),))

        self.coordinator.advance(planners=False)

        # Let a worker that should never have started run to completion, so the
        # ledger damage is asserted instead of only the worker count.
        for worker in tuple(self.coordinator._workers.values()):
            await asyncio.wait({worker})
        self.assertEqual(self.read_task("delivery-1").state, "created",
                         "a transient capacity refusal must leave the delivery queued, never cancelled")
        self.assertEqual(self.delivery.cancelled, [])
        self.assertEqual(len(self.coordinator._workers), 0,
                         "an exact claim must not start while the lane slot is already held")

        self.tasks.finish(holder, TaskResult("succeeded")).unwrap()
        self.assertEqual(self.tasks.held(Lane.BACKGROUND).unwrap(), 0)

        self.coordinator.advance(planners=False)

        self.assertIn("delivery-1", self.coordinator._workers)
        worker = self.coordinator._workers["delivery-1"]
        await asyncio.wait({worker})
        result = worker.result().unwrap()
        self.assertIsNotNone(result.task, "the released slot must serve the queued delivery")
        self.assertEqual(result.task.state, "succeeded")
        self.assertEqual(self.delivery.delivered, ["delivery-1"])
        self.assertEqual(self.tasks.held(Lane.BACKGROUND).unwrap(), 0)


class JudgeSelfValidationTests(ExecutionFixture):
    """A judge task must accept the verdict it wrote itself, and nothing else."""

    CONTACT = "contact-1"
    JUDGE_TASK = "contact-judge-1"

    def setUp(self):
        super().setUp()
        self.contacts = ProactiveContacts(_Configuration(self.runtime))
        # `attach()` binds this guard in production; the validator itself needs no host.
        self.contacts.require_running = lambda: None

    def seed(self, *, decision, judge_task_id, judge_state, contact_id=CONTACT):
        """Write the draft and its operation row exactly as the judge commit leaves them."""
        operation_id = "operation-" + contact_id
        at = stamp(self.clock.now())
        record = '{"decision": "%s", "judge": {"task_id": "%s", "state": "%s"}}' % (
            decision, judge_task_id, judge_state)
        with self.runtime.transaction() as connection:
            connection.execute("DELETE FROM proactive_contacts WHERE contact_id = ?", (contact_id,))
            connection.execute("DELETE FROM operations WHERE operation_id = ?", (operation_id,))
            connection.execute(
                """INSERT INTO operations (operation_id, owner, installation_id, platform, scope_kind,
                    native_scope_id, lineage_id, operation_revision, idempotency_key, parameter_hash,
                    state, commit_state, created_at, updated_at)
                   VALUES (?, 'proactive', ?, 'fixture', 'private', ?, 'fixture', 1, ?, 'hash',
                           'completed', 'committed', ?, ?)""",
                (operation_id, INSTALLATION, self.context.key, "idempotency-" + contact_id, at, at))
            connection.execute(
                """INSERT INTO proactive_contacts (contact_id, task_id, origin_key, record_json, body,
                    payload_hash, operation_id, created_at)
                   VALUES (?, ?, ?, ?, 'body', 'payload-hash', ?, ?)""",
                (contact_id, judge_task_id, self.context.key, record, operation_id, at))

    def spec_for(self, *, task_id=JUDGE_TASK, contact_id=CONTACT):
        return TaskSpec(task_id, self.context, JUDGE_KIND, "fixture:judge-input", contact_id,
                        self.clock.now(), self.clock.now() + timedelta(minutes=5))

    def assert_rejected(self, spec):
        outcome = self.contacts.validate_judge(spec, self.clock.now())
        self.assertIsNotNone(outcome.failure, "a foreign or unfinished judgement must be rejected")
        self.assertEqual(outcome.failure.code, "contact_judge_unavailable")

    def test_pending_draft_passes_validation(self):
        self.seed(decision="judge_pending", judge_task_id=self.JUDGE_TASK, judge_state="pending")
        self.assertTrue(self.contacts.validate_judge(self.spec_for(), self.clock.now()).unwrap())

    def test_resolved_verdict_written_by_the_same_task_passes_validation(self):
        self.seed(decision="send", judge_task_id=self.JUDGE_TASK, judge_state="resolved")
        self.assertTrue(self.contacts.validate_judge(self.spec_for(), self.clock.now()).unwrap())

    def test_resolved_skip_from_the_same_task_passes_validation(self):
        self.seed(decision="skip", judge_task_id=self.JUDGE_TASK, judge_state="resolved")
        self.assertTrue(self.contacts.validate_judge(self.spec_for(), self.clock.now()).unwrap())

    def test_foreign_or_unfinished_judgement_is_rejected(self):
        cases = (
            ("resolved send from another task",
             dict(decision="send", judge_task_id="contact-judge-other", judge_state="resolved")),
            ("pending draft for another task",
             dict(decision="judge_pending", judge_task_id="contact-judge-other", judge_state="pending")),
            ("own task with an unfinished verdict",
             dict(decision="send", judge_task_id=self.JUDGE_TASK, judge_state="pending")),
            ("own task with an unknown decision",
             dict(decision="maybe", judge_task_id=self.JUDGE_TASK, judge_state="resolved")),
        )
        for label, seed in cases:
            with self.subTest(label):
                self.seed(**seed)
                self.assert_rejected(self.spec_for())

    def test_missing_draft_and_mismatched_origin_are_rejected(self):
        self.seed(decision="judge_pending", judge_task_id=self.JUDGE_TASK, judge_state="pending")
        self.assert_rejected(self.spec_for(contact_id="contact-missing"))
        with self.runtime.transaction() as connection:
            connection.execute("UPDATE proactive_contacts SET origin_key = 'another-window' WHERE contact_id = ?",
                               (self.CONTACT,))
        self.assert_rejected(self.spec_for())
