"""A proactive contact is the one writer that speaks on its own, so it is also the
only place a role may publish a public Zone entry without being asked.

These tests pin the three properties that make that safe: the Zone catalog only
reaches a contact when the extension is wired and its switches are on, a Zone
round is followed by a contact round in the same session, and the contact body
still has to be a valid contact decision.
"""

from zoneinfo import ZoneInfo
import json
import unittest

from companion_v2.conversation.tool_loop import specification
from companion_v2.execution.models import encode
from companion_v2.model_gateway.models import ToolCall, ToolExchange
from companion_v2.proactive.service import ZONE_FOLLOWUP
from tests.proactive_support import ContactFixture
from tests.test_role_tool_loop import answered, requested


ZONE_ACTIONS = ("qzone.feed.read", "qzone.post.publish")


class ZoneTools:
    """The smallest catalog the contact worker can read."""

    def __init__(self, catalog=(), exchanges=None):
        self.catalog = tuple(catalog)
        self.actions = frozenset(tool.action for tool in self.catalog)
        self.exchanges = exchanges or {}
        self.executed = []

    def catalog_for(self, context):
        return self.catalog

    async def execute_async(self, run, model_call_id, call):
        self.executed.append((model_call_id, call))
        result = self.exchanges.get(call.action, {"state": "succeeded", "payload": {}})
        return ToolExchange(call, encode(result))


class ZoneSettings:
    """The two reads ``_zone_opportunity`` performs, and nothing else."""

    def __init__(self, runtime, settings=None, state=None):
        self.runtime = runtime
        self.settings = settings or {}
        self._state = state

    def configuration(self, context, at):
        return dict(self.settings)

    def state(self, context):
        return self._state


class SimpleState:
    def __init__(self, publish_day="", publish_count=0):
        self.publish_day, self.publish_count = publish_day, publish_count


class ProactiveZoneTests(ContactFixture, unittest.IsolatedAsyncioTestCase):
    def zone_catalog(self):
        return (specification("qzone.post.publish", ("text", "topic", "scene", "confidence")),
                specification("qzone.feed.read", ()), specification("memo.list", ()))

    def zone(self, settings=None, state=None, runtime=None):
        settings = settings if settings is not None else {
            "enabled": True, "publish_enabled": True, "publish_max_daily": 1, "quiet_timezone": "Asia/Shanghai"}
        return ZoneSettings(runtime or self.runtime, settings, state or SimpleState())

    def publish_call(self):
        return ToolCall("zone-1", "qzone.post.publish", encode({
            "text": "今天的雨停得很慢。", "topic": "mood", "scene": "daily", "confidence": 0.8}))

    async def wired(self, zone=None):
        app = await self.enabled()
        tools = ZoneTools(self.zone_catalog())
        app.proactive.attach_tools(tools)
        app.proactive.attach_qzone(zone if zone is not None else self.zone())
        return app, tools

    async def test_a_contact_without_a_wired_extension_stays_tool_free(self):
        app = await self.enabled()
        tools = ZoneTools(self.zone_catalog())
        app.proactive.attach_tools(tools)
        await self.contact(app)
        self.assertEqual(self.called[-1].tools, ())
        self.assertEqual(tools.executed, [])

    async def test_the_recorded_contact_envelope_survives_the_real_wire_builder(self):
        """真回归：把实际发给模型的信封喂给真正的 build_wire。

        上一版测试只用一个记录信封的假网关，永远发现不了
        ``private writing does not offer tools``——那道检查在
        ``model_wire.build_wire`` 里，直到真机本地预估阶段才炸。
        这里直接调用真实 wire 构建，钉住「结构化输出不带目录」。
        """
        from companion_v2.adapters.astrbot.model_wire import build_wire
        from companion_v2.model_gateway.models import ModelEnvelope

        app, tools = await self.wired()
        await self.contact(app)
        envelope = self.called[-1]
        self.assertEqual(envelope.original.output_format, "proactive_contact")
        # 与 ModelSession 真正下发的信封同形：original + 本轮目录 + 工具历史。
        wire = build_wire(ModelEnvelope(original=envelope.original, task_prompt="",
                                        max_output_tokens=512, configuration_token="t",
                                        tools=envelope.tools, tool_history=envelope.tool_history))
        self.assertEqual(tuple(wire.tools), ())

    async def test_the_zone_invitation_reaches_the_contact_prompt_when_the_extension_is_running(self):
        app, tools = await self.wired()
        await self.contact(app)
        envelope = self.called[-1]
        # 目录本身不下发（结构化输出），邀请文本仍然进提示词。
        self.assertEqual(envelope.tools, ())
        self.assertIn("qzone.post.publish", envelope.original.instruction)
        self.assertIn("今天还能发 1 条", envelope.original.instruction)

    async def test_a_switched_off_publish_never_offers_the_zone(self):
        app, tools = await self.wired(self.zone({"enabled": True, "publish_enabled": False}))
        await self.contact(app)
        self.assertEqual(self.called[-1].tools, ())
        self.assertNotIn("qzone.post.publish", self.called[-1].original.instruction)

    async def test_the_daily_quota_withdraws_the_offer(self):
        today = self.clock.now().astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        app, tools = await self.wired(self.zone(state=SimpleState(today, 1)))
        await self.contact(app)
        self.assertEqual(self.called[-1].tools, ())

    async def test_the_zone_catalog_is_offered_to_the_followup_round_only(self):
        """回归：开口轮不带目录（结构化输出），续轮才回放工具结果。

        7.1.0 的 ``model_wire.build_wire`` 对非 conversation 输出直接拒绝工具目录，
        所以「主动联系顺带发空间」只能走续轮：首轮不给目录，模型不可能在本轮
        调用空间；一旦它真的调用了（例如模型忽略约束），会话以
        ``model_tools_not_offered`` 整轮失败，绝不会把空间正文当私聊发出去。
        """
        app, tools = await self.wired()
        session = None

        async def behavior(envelope):
            return answered(json.dumps({"decision": "send", "text": "想起你还醒着。"}, ensure_ascii=False))

        self.model_behavior = behavior
        task = (await self.contact(app)).unwrap().task
        self.assertEqual(task.state, "succeeded")
        # 开口轮：目录为空是「7.1.0 结构化输出的硬约束」，不是 bug。
        self.assertEqual(self.called[-1].original.output_format, "proactive_contact")

    async def test_a_zone_round_cannot_hijack_a_structured_contact(self):
        app, tools = await self.wired()
        tools.exchanges["qzone.post.publish"] = {"state": "succeeded", "payload": {"published": True}}
        rounds = []

        async def behavior(envelope):
            rounds.append(envelope)
            if len(rounds) == 1:
                return requested(self.publish_call())
            return answered(json.dumps({"decision": "send", "text": "刚写完一句话，想起你还醒着。"}, ensure_ascii=False))

        self.model_behavior = behavior
        task = (await self.contact(app)).unwrap().task
        # 7.1.0 起开口轮不再携带目录（结构化输出不允许 tools），续轮也就不会出现：
        # 首轮若仍给出工具调用，会话以 model_tools_not_offered 整轮失败，
        # 空间正文永远不会变成用户读到的私聊消息。
        self.assertEqual(task.state, "failed")
        self.assertEqual(tools.executed, [])
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].original.output_format, "proactive_contact")

    async def test_a_zone_round_never_becomes_the_message_the_user_reads(self):
        app, tools = await self.wired()
        rounds = []

        async def behavior(envelope):
            rounds.append(envelope)
            return answered('{"decision":"skip","text":"","skip_reason":"repetitive"}')

        self.model_behavior = behavior
        task = (await self.contact(app)).unwrap().task
        self.assertEqual(task.state, "succeeded")
        self.assertTrue(task.result_ref.startswith("contact-skipped:"))
        self.assertEqual(len(rounds), 1)

    async def test_a_structured_contact_never_hands_the_zone_catalog_to_the_wire(self):
        """回归：主动联系是结构化输出，带工具目录会在 model_wire 预检 ValueError。

        真机曾因此整轮失败（``model_estimation_failed`` / ``private writing does
        not offer tools``），表现为主动联系恒不发出。这里钉住两点：目录仍然算出来了
        （机会可用），但结构化请求上不会真的交给会话。
        """
        app, tools = await self.wired()
        rounds = []

        async def behavior(envelope):
            rounds.append(envelope)
            return answered(json.dumps({"decision": "send", "text": "想起你还醒着。"}, ensure_ascii=False))

        self.model_behavior = behavior
        task = (await self.contact(app)).unwrap().task
        self.assertEqual(task.state, "succeeded")
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].original.output_format, "proactive_contact")

    async def test_a_contact_that_never_decides_fails_instead_of_sending_zone_text(self):
        app, tools = await self.wired()

        async def behavior(envelope):
            return requested(self.publish_call())

        self.model_behavior = behavior
        task = (await self.contact(app)).unwrap().task
        self.assertEqual(task.state, "failed")
        self.assertFalse((task.result_ref or "").startswith("contact-sent:"))
        # 7.1.0 起，主动联系的第一轮（开口轮）必须直接产出结构化正文，所以
        # 会话首轮不给工具目录；调用方显式传 ()，ModelSession 再以
        # ``model_tools_not_offered`` 拒绝，整轮因此失败而不是把空间正文
        # 当成私聊消息发出去。这条断言钉住的就是「永远不会变成用户看到的正文」。
        self.assertEqual(tools.executed, [])
