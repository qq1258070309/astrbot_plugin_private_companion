"""Install and consent for the included Zone extension, per role and per window.

Reality's access service is the shape being copied, with one difference: the
package is published by V2 itself, so the descriptor is a repository constant
instead of a declaration reported by another Star. Everything that makes the
capability usable stays explicit -- catalog registration, a pinned installation,
the role switch, per-capability consent and the identity grant -- because the
plugin being loaded proves nothing about the operator wanting it.
"""

from __future__ import annotations

from companion_v2.capabilities.models import CapabilityAuthorizationState, CapabilityDesiredState
from companion_v2.capabilities.repositories import CapabilityRepository
from companion_v2.execution.models import TaskError, digest, encode, require
from companion_v2.foundation.refs import OperationRef, ScopeKind, VersionRef
from companion_v2.identity_policy.models import AuthorizationTier, GrantState
from companion_v2.identity_policy.object_access import ObjectAccessPolicy
from companion_v2.identity_policy.personas import PersonaDirectory
from companion_v2.identity_policy.repository import PersistentIdentityDirectory
from companion_v2.qzone.capability import CAPABILITIES, EXTENSION, PUBLISH_ACTION
from companion_v2.qzone.capability import package_descriptor
from companion_v2.qzone.topics import SCENES, TOPIC_SPECS, allowed_scenes
from companion_v2.storage.codec import scope_values
from companion_v2.storage.models import OperationState
from companion_v2.storage.repositories import OperationRepository


OWNER = "capability.qzone-access"
INVOKE_CAPABILITY = "extension.tool.invoke"
# The zones this role owns; see ``_person_scope``.
PRIVATE_ZONES = "private-zones"


def package():
    return package_descriptor()


def catalogue(settings=None):
    """The topic and scene vocabulary the page offers, from the one catalogue.

    ``scenes`` is what this role may actually publish into right now: the
    topic's declared scenes narrowed by the configured ``<topic>_scenes`` list,
    so a page selection can never be one the gate would refuse. The declared set
    stays visible as ``declared_scenes`` rather than being silently dropped.
    """
    values = settings if isinstance(settings, dict) else {}
    topics = []
    for item in TOPIC_SPECS:
        declared = [scene.value for scene in item.scenes]
        configured = values.get(f"{item.topic.value}_scenes")
        if isinstance(configured, str) and configured.strip():
            try:
                allowed = [scene for scene in allowed_scenes(configured) if scene.value in declared]
            except ValueError:
                # A broken configured list must not empty the picker: the gate
                # refuses the same value, so showing what the topic declares is
                # the honest fallback.
                effective = declared
            else:
                effective = [scene.value for scene in allowed] or declared
        else:
            effective = declared
        topics.append({"id": item.topic.value, "label": item.label, "guidance": item.guidance,
                       "scenes": effective, "declared_scenes": declared,
                       "enabled": bool(values.get(f"{item.topic.value}_enabled", True))})
    return {"topics": topics, "scenes": dict(SCENES)}


def _person_scope(runtime, context):
    """The persona routes where this participant is the private owner.

    Consent was being written into a single private window, so the Zone tools
    only ever appeared in the one chat the operator happened to be in when they
    pressed the switch: a second account of the same person, or the proactive
    worker composing into another window, saw no tools at all and nothing in the
    Zone state recorded a refusal. The person, not the chat, owns this switch.

    Groups, and threads whose parent is a group, are never included; a group's
    speaker is not its owner. An owner whose own window cannot be resolved falls
    back to the requested scope alone, which keeps the previous behaviour.
    """
    own = [context.scope] + [route.scope for route in PersonaDirectory(runtime).routes()
                             if route.scene_kind is ScopeKind.PRIVATE
                             and route.user is not None and route.user == context.actor.subject]
    unique = {}
    for scope in own:
        unique[(scope.key, scope.conversation_id, scope.session_id)] = scope
    return tuple(unique[key] for key in sorted(unique))


def _replace_authorization(repository, *, capability, subject, scope, active, at):
    """Point this person's retained consent at ``scope`` (or drop it there).

    Idempotent on purpose: one switch press may revisit the same window through
    both the person-wide sweep and the original requested-scope write.
    """
    target = CapabilityAuthorizationState.ACTIVE if active else CapabilityAuthorizationState.REVOKED
    consent = repository.consent(extension_id=EXTENSION, capability_id=capability,
                                 subject=subject, scope=scope)
    if not consent.is_success:
        if not active:
            return
        expected = 0
    else:
        current = consent.unwrap()
        if current.state is target:
            return
        expected = current.revision
    repository.set_authorization(extension_id=EXTENSION, capability_id=capability,
        subject=subject, scope=scope, state=target, expected_revision=expected, observed_at=at).unwrap()


class QzoneAccess:
    """One authenticated entry point shared by the page, commands and tools."""

    def __init__(self, application, context, *, service=None, credential_state=None):
        self.application = application
        self.context = context
        self.service = service
        # Kept for callers that resolve the conclusion themselves (a plain dict or a
        # getter). With a service present, ``status()`` takes the conclusion from it,
        # because a construction-time copy goes stale the moment the same request
        # acquires a fresh credential.
        self.credential_state = credential_state
        self.runtime = application.runtime
        self.repository = CapabilityRepository(self.runtime)
        self.identities = PersistentIdentityDirectory(self.runtime)
        self.policy = ObjectAccessPolicy(self.runtime)
        self.package = package()

    def _credential(self):
        """The page-facing credential row, resolved when the status is built."""
        state = self.credential_state() if callable(self.credential_state) else self.credential_state
        return dict(state or {})

    def _access(self, operator, at, *, action="capability.view"):
        context = self.context
        if context.scope.kind is not ScopeKind.PRIVATE:
            raise TaskError("qzone_private_required", "QQ 空间只在私聊目标下管理")
        require(self.application.tasks.authorize_context(context, action="conversation.reply", observed_at=at))
        require(self.policy.authorize(operator, scope=context.scope, action=action,
                                     owner=context.actor.subject, observed_at=at))

    def _installation(self):
        result = self.repository.installation(extension_id=EXTENSION)
        return result.unwrap() if result.is_success else None

    def _selection(self):
        context = self.context
        installed = self._installation()
        if installed is None:
            return None
        projection = self.repository.projection(extension_id=EXTENSION, role=context.role_binding.role,
                                               scope=context.scope)
        return projection.unwrap().role_selection if projection.is_success else None

    def _consents(self):
        context = self.context
        rows = {}
        for capability in CAPABILITIES:
            row = self.runtime.read_one("""SELECT state, revision FROM capability_authorizations
                WHERE extension_id = ? AND capability_id = ? AND subject_kind = ? AND subject_id = ?
                  AND installation_id = ? AND platform = ? AND scope_kind = ? AND native_scope_id = ?
                  AND bot_id = ? AND account_id = ? AND conversation_id = ? AND session_id = ?""",
                (EXTENSION, capability, context.actor.subject.kind.value, context.actor.subject.subject_id,
                 *scope_values(context.scope)))
            rows[capability] = dict(row) if row is not None else None
        return rows

    def _zone(self, scope):
        """An owner scope as the page shows it; the account never appears in the label."""
        route = PersonaDirectory(self.runtime).route(scope)
        user = route.user.subject_id if route is not None and route.user is not None else ""
        return {"conversation_id": scope.conversation_id, "scene_kind": scope.kind.value,
                "owner": user.rsplit(":", 1)[-1] if user else "", "session_id": scope.session_id}

    def _extend_invoke_grants(self, context, zones, *, at):
        """Let the Zone tools follow the person into their other own windows.

        Each switch press used to mint one grant for one window, keyed by that
        command, and the next press minted a second grant for the same window:
        the directory then matched two identical grants and answered
        ``scope_not_granted``, so the tools stopped appearing even in the window
        the operator had just authorised. Grants are now keyed by the window and
        issued once; a window that is already granted is left alone.
        """
        subject = context.actor.subject
        held = {grant.scope.key for grant in self.identities.grants_for_subject(subject)
                if grant.capability == INVOKE_CAPABILITY and grant.state is GrantState.ACTIVE}
        pending = [scope for scope in zones if scope.key not in held]
        if not pending:
            return
        binding = next(item for item in self.identities.snapshot().bindings
                       if item.binding_id == context.actor.binding_id)
        for scope in pending:
            self.identities.issue_grant(grant_id="qzone-invoke:" + digest([EXTENSION, scope.key]),
                subject=subject, scope=scope, capability=INVOKE_CAPABILITY,
                tier=AuthorizationTier.STANDARD, valid_from=at, expires_at=binding.expires_at,
                expected_revision=self.identities.revision)

    def _token(self, state):
        return digest([EXTENSION, self.context.key, encode(self.package),
                       [encode(item) if item is not None else None for item in state],
                       self.identities.revision, self.policy.revision])

    def status(self, operator, at):
        self._access(operator, at)
        with self.runtime.read_snapshot():
            installed, selection, consents = self._installation(), self._selection(), self._consents()
            same = installed is not None and (
                installed.package_id, installed.package_version, installed.artifact_hash
            ) == (self.package.package_id, self.package.package_version, self.package.artifact_hash)
            active = bool(same and installed.desired_state is CapabilityDesiredState.ACTIVE)
            role_enabled = bool(selection and selection.enabled)
            consented = {capability: bool(row and row["state"] == CapabilityAuthorizationState.ACTIVE.value)
                         for capability, row in consents.items()}
            granted = self.identities.authorize(self.context.actor, scope=self.context.scope,
                                                capability=INVOKE_CAPABILITY, observed_at=at).is_success
            publish_granted = self.identities.authorize(self.context.actor, scope=self.context.scope,
                                                        capability=PUBLISH_ACTION, observed_at=at).is_success
            reason = ("qzone_not_installed" if installed is None else
                      "qzone_package_changed" if not same else
                      "qzone_not_active" if not active else
                      "qzone_role_disabled" if not role_enabled else
                      "qzone_consent_missing" if not any(consented.values()) else
                      "qzone_grant_missing" if not (granted and publish_granted) else "")
            runtime = self.service.status(self.context, at) if self.service is not None else {}
            runtime = dict(runtime or {})
            # ``QzoneService.status`` states the credential conclusion in the same
            # read; it is presented at the top level because that is the row the
            # page renders, and it must not lag behind an acquisition that already
            # happened earlier in this request.
            credential = runtime.pop("credential", None)
            if credential is None:
                credential = self._credential()
            return {"extension_id": EXTENSION, "package_version": self.package.package_version,
                    "installed": installed is not None, "active": active, "role_enabled": role_enabled,
                    "consented": consented, "invoke_granted": granted, "publish_granted": publish_granted,
                    "grant_zones": [self._zone(scope) for scope in _person_scope(self.runtime, self.context)],
                    "credential": dict(self.credential_state or {}), "runtime": runtime,
                    "credential": dict(credential or {}), "runtime": runtime,
                    "capabilities": list(CAPABILITIES),
                    "catalogue": catalogue((runtime or {}).get("settings")),
                    "edit_token": self._token((installed, selection, consents))}

    def configure(self, operator, command, at):
        self._access(operator, at, action="capability.consent.set")
        require(self.policy.scope_access(operator, scope=self.context.scope, action="capability.role.set",
                                         observed_at=at, core_only=True))
        if (type(command) is not dict or set(command) != {"operation_key", "edit_token", "enabled"}
                or type(command["enabled"]) is not bool
                or any(type(command[key]) is not str or not command[key].strip() or len(command[key]) > 160
                       for key in ("operation_key", "edit_token"))):
            raise TaskError("qzone_request_invalid", "an explicit scoped install command is required")
        context = self.context
        key = digest([context.key, operator.subject.subject_id, command["operation_key"]])
        operation = OperationRef("qzone-access:" + key, OWNER, context.scope, VersionRef(key, 1), key)
        operations = OperationRepository(self.runtime)
        with self.runtime.transaction():
            receipt = require(operations.reserve(operation, parameter_hash=digest([
                encode(operator.principal), encode(operator.subject), operator.binding_id,
                operator.binding_revision, context.key, command]), observed_at=at))
            if receipt.replayed:
                if receipt.state is not OperationState.COMPLETED:
                    raise TaskError("capability_operation_unresolved", "the original install command is unresolved")
                return {"replayed": True, "status": self.status(operator, at)}
            state = (self._installation(), self._selection(), self._consents())
            zones = _person_scope(self.runtime, context)
            if command["edit_token"] != self._token(state):
                raise TaskError("qzone_access_changed", "refresh the changed install settings before saving")
            installed, selection, consents = state
            enabled = command["enabled"]
            if enabled:
                require(self.repository.register_descriptor(self.package, registered_at=at))
                if installed is None:
                    installed = require(self.repository.acquire(extension_id=EXTENSION,
                        package_id=self.package.package_id, package_version=self.package.package_version,
                        expected_revision=0, observed_at=at))
                elif (installed.package_id, installed.package_version, installed.artifact_hash) != (
                        self.package.package_id, self.package.package_version, self.package.artifact_hash):
                    raise TaskError("qzone_package_changed", "the selected package differs from the included one")
                if installed.desired_state is not CapabilityDesiredState.ACTIVE:
                    raise TaskError("qzone_not_active", "the selected QQ Zone package is paused or discarded")
                if not selection or not selection.enabled:
                    require(self.repository.set_role_enabled(extension_id=EXTENSION,
                        role=context.role_binding.role, bot_id=context.scope.bot_id, enabled=True,
                        expected_revision=selection.revision if selection else 0, observed_at=at))
                self._extend_invoke_grants(context, zones, at=at)
            # Revocation only clears this participant's consent; the role switch and
            # the installed package stay as the admin set them.
            if installed is not None:
                others = tuple(scope for scope in zones if scope.key != context.scope.key)
                for capability in CAPABILITIES:
                    for scope in others:
                        _replace_authorization(self.repository, capability=capability,
                                               subject=context.actor.subject, scope=scope, active=enabled, at=at)
                    if enabled:
                        row = consents.get(capability)
                        require(self.repository.set_authorization(extension_id=EXTENSION, capability_id=capability,
                            subject=context.actor.subject, scope=context.scope,
                            state=CapabilityAuthorizationState.ACTIVE,
                            expected_revision=row["revision"] if row else 0, observed_at=at))
                    else:
                        _replace_authorization(self.repository, capability=capability,
                                               subject=context.actor.subject, scope=context.scope, active=False, at=at)
            require(operations.transition(operation.operation_id, expected_state=OperationState.ACCEPTED,
                                          next_state=OperationState.COMPLETED, observed_at=at))
            return {"replayed": False, "status": self.status(operator, at)}


__all__ = ["INVOKE_CAPABILITY", "OWNER", "QzoneAccess", "package"]
