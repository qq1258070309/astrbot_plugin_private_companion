"""The contact planner is off the AstrBot event loop, but task activation stays on it."""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

from companion_v2.proactive.scheduling import ContactSchedule


class ContactScheduleOffloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_advance_async_plans_in_worker_and_activates_on_loop(self):
        scheduler = object.__new__(ContactSchedule)
        scheduler._closed = False
        scheduler._advancing = False
        scheduler._workers = {}
        scheduler.tasks = SimpleNamespace(now=lambda: object())
        scheduler._cursor = 1
        scheduler._native_cursor = 1
        row = {"origin_key": "origin", "sequence": 1}
        plan = ("plan",)

        seen = {}
        loop_thread = threading.get_ident()
        scheduler._begin_tick = lambda: (object(), (row,), 1, 1, 0)
        scheduler._row_cursor = lambda current: seen.setdefault("cursor", current)

        def plan_one(current, now):
            seen["plan_thread"] = threading.get_ident()
            threading.Event().wait(0.05)
            return plan

        def activate(current, current_plan, available, now):
            seen["activate_thread"] = threading.get_ident()
            seen["plan"] = current_plan
            return available - 1

        scheduler._plan_one = plan_one
        scheduler._activate_plan = activate
        scheduler._note_coordinator = lambda *args: seen.setdefault("coordinator_thread", threading.get_ident())

        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(3):
                await asyncio.sleep(0.005)
                ticks += 1

        await asyncio.gather(ticker(), scheduler.advance_async())
        self.assertNotEqual(seen["plan_thread"], loop_thread)
        self.assertEqual(seen["activate_thread"], loop_thread)
        self.assertEqual(seen["coordinator_thread"], loop_thread)
        self.assertEqual(seen["plan"], plan)
        self.assertGreater(ticks, 0, "event loop must keep running while candidate sources are evaluated")

    async def test_close_waits_for_inflight_planner_before_closing_sources(self):
        scheduler = object.__new__(ContactSchedule)
        scheduler._closed = False
        scheduler._workers = {}
        scheduler._judges = {}
        for name in ("events", "growth_events", "journal_events", "calendar_events",
                     "reminiscence_events", "weather_events", "weather_change_events",
                     "official_alert_events"):
            setattr(scheduler, name, None)
        seen = {}
        planning = asyncio.create_task(asyncio.sleep(0.05))
        scheduler._planning = planning

        class Source:
            def close(self):
                seen["closed_after_planner"] = planning.done()

        scheduler.balance_events = Source()
        scheduler.news_events = Source()
        scheduler.screen_events = Source()

        await scheduler.close()
        self.assertTrue(seen["closed_after_planner"], "planner must finish before sources close")
        self.assertTrue(planning.done())


class ContactScheduleHoldTests(unittest.TestCase):
    """A gated window must be parked at the lift time, not left looking overdue.

    Without the write-back every following tick re-plans the same row, skips it
    again, and the schedule row keeps showing a start time that is long past.
    """

    NOW = datetime(2026, 11, 3, 5, 56, 27, tzinfo=timezone.utc)

    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / f"contact-hold-{os.urandom(6).hex()}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "hold.sqlite3")
        self.db.execute("CREATE TABLE role_state_schedules (context_key TEXT PRIMARY KEY, next_at TEXT, enabled INTEGER)")
        self.db.execute("INSERT INTO role_state_schedules VALUES ('context-a', ?, 1)",
                        (self.NOW.isoformat(),))
        self.db.commit()

        class Runtime:
            def __init__(self, connection):
                self.connection = connection

            def transaction(self):
                db = self.connection

                class Transaction:
                    def __enter__(self):
                        db.execute("BEGIN IMMEDIATE")
                        return db

                    def __exit__(self, *_error):
                        db.commit()
                        return False

                return Transaction()

        self.runtime = Runtime(self.db)

    def tearDown(self):
        self.db.close()

    def scheduler(self, *, busy=None, sleep=None):
        scheduler = object.__new__(ContactSchedule)
        scheduler.runtime = self.runtime
        scheduler._note_window = lambda *args, **kwargs: None
        scheduler._busy_hold = lambda context, origin, now: busy
        scheduler._sleep_hold = lambda context, origin, now: sleep
        scheduler.contacts = SimpleNamespace(
            platform_circuit=SimpleNamespace(cooldown_until=lambda context, at: None))
        return scheduler

    def parked(self):
        row = self.db.execute("SELECT next_at FROM role_state_schedules WHERE context_key = 'context-a'").fetchone()
        return datetime.fromisoformat(row[0])

    @staticmethod
    def context():
        return SimpleNamespace(key="context-a")

    def test_a_busy_gate_parks_the_row_at_its_lift_time(self):
        lift = self.NOW + timedelta(minutes=12)
        scheduler = self.scheduler(busy=lift)
        available = scheduler._activate_plan({"origin_key": "context-a"}, (self.context(), None, (), "", {}),
                                             1, self.NOW)
        self.assertEqual(available, 1)  # A gate queues nothing, so it consumes no capacity.
        self.assertEqual(self.parked(), lift)

    def test_a_sleep_gate_parks_the_row_at_its_wake_time(self):
        wake = self.NOW + timedelta(hours=7)
        scheduler = self.scheduler(sleep=wake)
        self.assertEqual(
            scheduler._activate_plan({"origin_key": "context-a"}, (self.context(), None, (), "", {}), 1, self.NOW), 1)
        self.assertEqual(self.parked(), wake)


if __name__ == "__main__":
    unittest.main()
