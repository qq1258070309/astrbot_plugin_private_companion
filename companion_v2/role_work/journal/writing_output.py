"""Parse storage structure only; literary quality belongs in the instructions."""

import json

from .models import DreamRecall, JournalDerivatives, JournalDraft, JournalKind


class JournalOutputError(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


def object_output(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate writing field")
            value[key] = item
        return value
    raw = text.strip()
    # 模型常把整段合法 JSON 包在 ```json 围栏里；剥掉围栏再解析，
    # 否则日记/选材会被误判成 unhandled_exception。
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("writing output must be an object")
    return value


def _candidates(text):
    """Yield JSON payloads from a reply that may wrap them in prose or a code fence."""
    text = text.strip()
    yield text
    if "```" in text:
        parts = text.split("```")
        for index in range(1, len(parts), 2):
            block = parts[index]
            if block.lstrip().startswith("json"):
                block = block.lstrip()[4:]
            block = block.strip()
            if block:
                yield block
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        yield text[start:end + 1]


def _decode(text):
    last = None
    for candidate in _candidates(text):
        try:
            return object_output(candidate)
        except ValueError as error:
            last = error
    if last is None:
        raise ValueError("writing output must be an object")
    # 7.1.5 起 writing 层把任何 ValueError 折成 TaskError(journal_output_invalid)，
    # 账本里的 detail 只剩 TaskError 自己的消息。把原始异常类型名写进消息，
    # 才能在 execution_attempts 里分清「JSON 解析失败」和「形状不合法」。
    raise ValueError(f"{type(last).__name__}: {last}") from last


def _pick(value, fields):
    """Reject unknown keys that carry content; tolerate explicitly empty ones."""
    extra = {key: item for key, item in value.items() if key not in fields}
    if any(item not in (None, "", [], {}) for item in extra.values()):
        raise ValueError("writing result must contain only its body fields")
    return value


def _recall(value):
    """Accept null, the three enum members, and their common textual variants."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in ("none", "null", "no", "无", "没有", "否"):
            return None
        aliases = {"完整": "full", "全": "full", "片段": "fragments", "碎": "fragments",
                   "余韵": "afterglow", "余味": "afterglow"}
        text = aliases.get(text, text)
        for member in DreamRecall:
            if member.value == text or member.name.lower() == text:
                return member
    raise ValueError("recall is not a remembered state")


def _relabel(value, job):
    """Turn a dream-labelled reply into a diary when the task asked for a diary.

    The shape is a storage concern: a diary entry has a body and no dream label. A model
    that returns ``recall``/``afterglow`` slots for a diary is describing mood, not
    demanding a different record type, so the fields are dropped instead of the writing.

    A *filled* afterglow used to abort the whole entry ("a diary cannot carry a dream
    afterglow"), which threw away a perfectly good diary over a spare mood field. The
    mood text is now folded into the body when the body is empty and dropped otherwise,
    so the writing survives either way.
    """
    if job.target.key.kind is JournalKind.DREAM or not isinstance(value, dict):
        return value
    value = dict(value)
    value.pop("recall", None)
    afterglow = value.pop("afterglow", None)
    if isinstance(afterglow, str) and afterglow.strip():
        body = value.get("body")
        if not isinstance(body, str) or not body.strip():
            value["body"] = afterglow
    return value


def draft_output(text, job):
    # 我方修复（7.0.0 起）：模型有时把 JSON 包在说明文字或 ```json 围栏里，
    # 直接 json.loads 会整篇丢弃；_decode 会依次尝试整段、围栏块、首尾花括号。
    # 日记里模型习惯性多带 recall/afterglow：_relabel 先把情绪文字折进正文再校验形状。
    value = _decode(text)
    if set(value) != {"body", "form", "recall", "afterglow"}:
        raise ValueError("writing result must contain only its body fields")
    value = _relabel(value, job)
    if job.target.key.kind is JournalKind.DIARY:
        body = value.get("body")
        if not isinstance(body, str) or not body.strip():
            raise JournalOutputError("journal_diary_body_missing", "diary output needs a nonempty body")
        return JournalDraft(job.target, body=body, form=value["form"], recall=None,
                            afterglow="", sources=job.sources, activities=job.activities,
                            journals=job.recent, materials=job.materials)
    recall = _recall(value.get("recall"))
    body = value.get("body")
    afterglow = value.get("afterglow")
    if body is None:
        body = ""
    if afterglow is None:
        afterglow = ""
    if not isinstance(body, str) or not isinstance(afterglow, str):
        raise ValueError("writing body must be text")
    if job.target.key.kind is JournalKind.DREAM:
        if recall is DreamRecall.AFTERGLOW:
            if body.strip() or not afterglow.strip():
                raise ValueError("afterglow-only recall cannot manufacture a dream body")
        elif not body.strip():
            raise ValueError("remembered dream or fragments need their body")
    else:
        # 日记只有正文，梦的槽位一律丢弃（_relabel 已把情绪文字折进正文）。
        recall = None
        afterglow = ""
        if not body.strip():
            raise ValueError("a diary needs its body")
    return JournalDraft(job.target, body=body, form=value.get("form") or "", recall=recall,
                        afterglow=afterglow, sources=job.sources, activities=job.activities,
                        journals=job.recent, materials=job.materials)


def derivatives_output(text, parent):
    value = object_output(text)
    if set(value) != {"summary", "dream_fragments", "continuity"}:
        raise ValueError("derived result must contain only its material fields")
    fragments = value["dream_fragments"]
    if not isinstance(fragments, list) or len(fragments) > 32:
        raise ValueError("derived fragments are not a bounded list")
    texts, origins = [], []
    known = {item.material_id for item in parent.draft.materials}
    for fragment in fragments:
        if not isinstance(fragment, dict) or set(fragment) != {"text", "material_ids"}:
            raise ValueError("fragment must retain its provenance")
        ids = fragment["material_ids"]
        if (not isinstance(ids, list) or any(not isinstance(item, str) or item not in known for item in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("fragment cannot invent or repeat material references")
        texts.append(fragment["text"])
        origins.append(tuple(ids))
    return JournalDerivatives(parent.reference, value["summary"], tuple(texts), value["continuity"], tuple(origins))
