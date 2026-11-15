"""Configuration storage ports; a field is persisted by exactly one owner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from contextlib import contextmanager
from contextvars import ContextVar
import json
from typing import Mapping, Protocol

from companion_v2.storage.codec import encode_timestamp
from companion_v2.storage.runtime import StorageRuntime

from .models import ConfigTarget, ConfigurationError, EffectiveValue, Scalar, encode
from .registry import FieldDefinition


# A read scope answers repeated reads of one target from the first answer. It is
# only ever entered around one synchronous discovery pass on the event-loop
# thread, and every writer in this tree runs on that same thread, so no write can
# land between two reads inside the scope: the cached answer is the same answer,
# not an older one. It exists because expression discovery asks for the same
# role-level target once per stored window -- 144 byte-identical reads per pass
# against a 361-row table, measured as the dominant share of a 30 s loop stall.
_READ_SCOPE: ContextVar[dict[tuple[str, str, tuple[str, ...]], "OwnerSnapshot"] | None] = (
    ContextVar("configuration_read_scope", default=None))


@contextmanager
def stable_repeated_reads():
    """Collapse repeated reads of one configuration target within this block."""
    token = _READ_SCOPE.set({})
    try:
        yield
    finally:
        _READ_SCOPE.reset(token)


@dataclass(frozen=True)
class OwnerSnapshot:
    revision: int
    dependencies: tuple[tuple[str, int], ...]
    fields: Mapping[str, EffectiveValue]
    lifecycle_token: str = ""


@dataclass(frozen=True)
class OwnerWrite:
    revision: int
    changed_fields: tuple[str, ...]


class ConfigurationOwner(Protocol):
    """Trusted, synchronous adapters participate in the caller's SQLite transaction."""

    owner_id: str
    runtime: StorageRuntime
    supports_reset: bool

    def read(self, target: ConfigTarget, fields: tuple[FieldDefinition, ...]) -> OwnerSnapshot: ...

    def preview_set(self, target: ConfigTarget, fields: tuple[FieldDefinition, ...], *,
                    changes: Mapping[str, Scalar]) -> Mapping[str, EffectiveValue]: ...

    def write(
        self, target: ConfigTarget, fields: tuple[FieldDefinition, ...], *,
        changes: Mapping[str, Scalar], reset: tuple[str, ...],
        expected_revision: int, observed_at: datetime,
    ) -> OwnerWrite: ...


class SparseConfigurationOwner:
    owner_id = "configuration"
    supports_reset = True

    def __init__(self, runtime: StorageRuntime) -> None:
        # ``runtime`` stays the main store for persona/route lookups; config
        # rows live in ``store``.  Splitting the two attributes is important:
        # owners such as growth/life need conversation_routes from the main
        # database while writing configuration_values to the side store.
        self.runtime = runtime
        self.store = runtime.configuration_store

    def read(self, target: ConfigTarget, fields: tuple[FieldDefinition, ...]) -> OwnerSnapshot:
        ids = tuple(field.field_id for field in fields)
        scope = _READ_SCOPE.get()
        scope_key = (self.owner_id, target.key, ids) if scope is not None else None
        if scope is not None:
            cached = scope.get(scope_key)
            if cached is not None:
                return cached
        placeholders = ",".join("?" for _ in ids)
        layers = target.chain()
        revision = 0
        dependencies = []
        records = {}
        for layer in layers:
            row = self.store.read_one("SELECT revision FROM configuration_targets WHERE target_key = ?", (layer.key,))
            revision = row["revision"] if row else 0
            records[layer.key] = {row["field_id"]: (json.loads(row["value_json"]), row["revision"]) for row in self.store.read_all(
                f"SELECT field_id, value_json, revision FROM configuration_values WHERE target_key = ? AND field_id IN ({placeholders})",
                (layer.key, *ids),
            )}
            # Keep the whole target revision for the transaction's write check,
            # but an open editor depends only on its requested fields. Otherwise
            # saving one model task invalidates every other task in the role.
            dependencies.append((layer.key, max((item[1] for item in records[layer.key].values()), default=0)))
        effective = {}
        for field in fields:
            value, source, source_revision = field.default, None, 0
            for layer in layers:
                if layer.layer in field.layers and field.field_id in records[layer.key]:
                    stored_value, source_revision = records[layer.key][field.field_id]
                    value = field.validate(stored_value)
                    source = layer
            effective[field.field_id] = EffectiveValue(value, source, source == target, source_revision)
        snapshot = OwnerSnapshot(revision, tuple(dependencies), effective)
        if scope is not None:
            scope[scope_key] = snapshot
        return snapshot

    def write(
        self, target: ConfigTarget, fields: tuple[FieldDefinition, ...], *,
        changes: Mapping[str, Scalar], reset: tuple[str, ...],
        expected_revision: int, observed_at: datetime,
    ) -> OwnerWrite:
        with self.store.transaction() as connection:
            row = connection.execute("SELECT revision FROM configuration_targets WHERE target_key = ?", (target.key,)).fetchone()
            revision = row["revision"] if row else 0
            if revision != expected_revision:
                raise ConfigurationError("configuration_revision_conflict", "configuration owner revision changed")
            timestamp = encode_timestamp(observed_at)
            connection.execute("INSERT OR IGNORE INTO configuration_targets VALUES (?, ?, 0, ?)", (target.key, encode(target.document()), timestamp))
            changed = []
            for key in sorted(set(changes).union(reset)):
                row = connection.execute("SELECT value_json FROM configuration_values WHERE target_key = ? AND field_id = ?", (target.key, key)).fetchone()
                if key in changes:
                    serialized = encode(changes[key])
                    if row is not None and row["value_json"] == serialized:
                        continue
                    connection.execute(
                        """INSERT INTO configuration_values VALUES (?, ?, ?, ?)
                           ON CONFLICT(target_key, field_id) DO UPDATE SET
                           value_json = excluded.value_json, revision = excluded.revision""",
                        (target.key, key, serialized, revision + 1),
                    )
                else:
                    if row is None:
                        continue
                    connection.execute("DELETE FROM configuration_values WHERE target_key = ? AND field_id = ?", (target.key, key))
                changed.append(key)
            revision += bool(changed)
            connection.execute("UPDATE configuration_targets SET revision = ?, updated_at = ? WHERE target_key = ?", (revision, timestamp, target.key))
        return OwnerWrite(revision, tuple(changed))

    def preview_set(self, target: ConfigTarget, fields: tuple[FieldDefinition, ...], *,
                    changes: Mapping[str, Scalar]) -> Mapping[str, EffectiveValue]:
        current = self.read(target, fields)
        result = dict(current.fields)
        for key, value in changes.items():
            if not result[key].explicit or result[key].value != value:
                result[key] = EffectiveValue(value, target, True, current.revision + 1)
        return result
