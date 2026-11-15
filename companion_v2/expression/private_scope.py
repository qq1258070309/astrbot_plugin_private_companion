"""Private-chat expression scope helpers.

Only private concerns live here: the participants bound to this role and the
private source contexts that belong to them. Scope-family resolution -- for both
private participants and group ownership -- lives in
``companion_v2.conversation.scope_family`` so the review page and reply
injection share one implementation instead of two entries.
"""

import json

from companion_v2.execution.models import TaskContext
from companion_v2.foundation.refs import ScopeKind


def _principal_key(principal):
    """The exact inputs ``resolve_authenticated`` reads, and nothing else."""
    return (principal.installation_id, principal.host_id, principal.platform,
            principal.native_account_id, principal.bot_id, principal.account_id)


def _scope_key(scope):
    """The exact inputs ``resolve_role`` reads, and nothing else."""
    return (scope.installation_id, scope.platform, scope.kind, scope.native_scope_id,
            scope.bot_id, scope.account_id, scope.conversation_id, scope.session_id)


def private_people(runtime, identity, context, at):
    """List only participants with a stored, currently bound private context for this role."""
    if context.scope.kind is not ScopeKind.PRIVATE:
        return ()
    candidates = {}
    # The source tables repeat one window's context hundreds of times, but the
    # identity answer depends only on the principal and scope inside it. Resolving
    # per row made a single discovery pay ~1,300 directory reads (two per row) to
    # learn something about five subjects. Both caches are exact rather than
    # approximate: the same principal and the same scope resolve identically at the
    # same instant, while the per-row revision comparison below still happens for
    # every row, so a stale observation is rejected exactly as before.
    resolved_cache = {}
    role_cache = {}
    scope_filter = """json_extract(context_json, '$.role_binding.role.subject_id') = ?
        AND json_extract(context_json, '$.role_binding.scope.bot_id') = ?
        AND json_extract(context_json, '$.role_binding.scope.installation_id') = ?"""
    parameters = (context.role_binding.role.subject_id, context.scope.bot_id,
                  context.scope.installation_id)
    for query in (
        "SELECT context_json FROM conversation_batches WHERE " + scope_filter + " ORDER BY rowid DESC LIMIT 2000",
        "SELECT context_json FROM conversation_native_observations WHERE kind = 'input' AND "
        + scope_filter + " ORDER BY observed_at DESC, rowid DESC LIMIT 2000",
    ):
        try:
            rows = runtime.read_all(query, parameters)
        except Exception:
            continue
        for row in rows:
            try:
                candidate = TaskContext.restore(json.loads(row["context_json"]))
            except (TypeError, ValueError, KeyError):
                continue
            if (candidate.scope.kind is not ScopeKind.PRIVATE
                    or candidate.scope.installation_id != context.scope.installation_id
                    or candidate.scope.bot_id != context.scope.bot_id
                    or candidate.role_binding.role != context.role_binding.role
                    or candidate.actor.subject.kind.value != "human"):
                continue
            subject_id = candidate.actor.subject.subject_id
            if subject_id in candidates:
                continue
            principal_key = _principal_key(candidate.actor.principal)
            resolved = resolved_cache.get(principal_key)
            if resolved is None:
                resolved = identity.resolve_authenticated(candidate.actor.principal, observed_at=at)
                resolved_cache[principal_key] = resolved
            scope_key = _scope_key(candidate.scope)
            current_role = role_cache.get(scope_key)
            if current_role is None:
                current_role = identity.resolve_role(candidate.scope, observed_at=at)
                role_cache[scope_key] = current_role
            if (not resolved.is_success or not current_role.is_success
                    or resolved.unwrap().subject != candidate.actor.subject
                    or resolved.unwrap().binding_id != candidate.actor.binding_id
                    or resolved.unwrap().binding_revision != candidate.actor.binding_revision
                    or current_role.unwrap() != candidate.role_binding):
                continue
            candidates[subject_id] = {
                "subject_id": subject_id,
                "label": candidate.actor.principal.native_account_id or subject_id,
                "platform": candidate.scope.platform,
                "scope_label": candidate.scope.native_scope_id,
            }
    selected = candidates.get(context.actor.subject.subject_id)
    if selected is not None:
        candidates[context.actor.subject.subject_id] = {
            **selected,
            "label": selected["label"] + " · 当前",
        }
    return tuple(sorted(candidates.values(), key=lambda item: (item["label"], item["subject_id"])))


def role_private_contexts(runtime, identity, messages, context, at):
    from .configuration import read_settings, source_subject_allowed_for_context

    people = private_people(runtime, identity, context, at)
    allowed_ids = {item["subject_id"] for item in people}
    contexts = {}
    # One window key can appear hundreds of times in the observation table. Its
    # admission depends on the restored context and configuration layers, never
    # on the row, so read those layers once per key. This loop runs synchronously
    # on the event loop and used to dominate a discovery pass.
    decisions = {}
    scope_filter = """json_extract(context_json, '$.role_binding.role.subject_id') = ?
        AND json_extract(context_json, '$.role_binding.scope.bot_id') = ?
        AND json_extract(context_json, '$.role_binding.scope.installation_id') = ?"""
    parameters = (context.role_binding.role.subject_id, context.scope.bot_id,
                  context.scope.installation_id)
    queries = (
        "SELECT context_json FROM conversation_batches WHERE " + scope_filter + " ORDER BY rowid DESC LIMIT 2000",
        "SELECT context_json FROM conversation_native_observations WHERE kind = 'input' AND "
        + scope_filter + " ORDER BY observed_at DESC, rowid DESC LIMIT 2000",
    )
    # The observation table repeats the same context_json many times per window.
    # An identical blob always restores the identical context, and admission is
    # already keyed by candidate.key, so skip the repeat before parsing it. This
    # loop runs on the event loop; avoiding thousands of throwaway restorations
    # per pass also slows long-running heap growth.
    seen_json = set()
    for query in queries:
        try:
            rows = runtime.read_all(query, parameters)
        except Exception:
            continue
        for row in rows:
            raw = row["context_json"]
            if raw in seen_json:
                continue
            seen_json.add(raw)
            try:
                candidate = TaskContext.restore(json.loads(raw))
            except (TypeError, ValueError, KeyError):
                continue
            subject_id = candidate.actor.subject.subject_id
            if candidate.key in contexts or subject_id not in allowed_ids:
                continue
            try:
                messages.authorize(candidate, at)
            except Exception:
                continue
            if candidate.key not in decisions:
                try:
                    policy = read_settings(runtime, candidate)
                    decisions[candidate.key] = bool(
                        candidate.scope.kind is ScopeKind.PRIVATE
                        and candidate.scope.installation_id == context.scope.installation_id
                        and candidate.scope.bot_id == context.scope.bot_id
                        and candidate.role_binding.role == context.role_binding.role
                        and policy.private_learning_enabled
                        and source_subject_allowed_for_context(runtime, candidate))
                except Exception:
                    decisions[candidate.key] = False
            if decisions[candidate.key]:
                contexts[candidate.key] = candidate
    return tuple(contexts.values())


def current_private_context(runtime, key, role_binding):
    """Recover an exact private source context by its opaque stable context key."""
    if type(key) is not str or len(key) != 64:
        return None
    rows = runtime.read_all("""SELECT context_json FROM conversation_batches WHERE origin_key = ?
        ORDER BY rowid DESC LIMIT 1""", (key,))
    if not rows:
        try:
            # Include the partial index predicate for native input lookups.
            rows = runtime.read_all("""SELECT context_json FROM conversation_native_observations
                WHERE context_key = ? AND kind = 'input' AND delivery_state = 'input_observed'
                ORDER BY observed_at DESC, rowid DESC LIMIT 1""", (key,))
        except Exception:
            rows = ()
    for row in rows:
        try:
            candidate = TaskContext.restore(json.loads(row["context_json"]))
        except (TypeError, ValueError, KeyError):
            continue
        if (candidate.key == key and candidate.scope.kind is ScopeKind.PRIVATE
                and candidate.scope.installation_id == role_binding.scope.installation_id
                and candidate.scope.bot_id == role_binding.scope.bot_id
                and candidate.role_binding.role == role_binding.role):
            return candidate
    return None
