from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


MAX_RESOLVED_APPROVALS = 1000


@dataclass
class ApprovalRequest:
    approval_request_id: str
    session_id: str
    turn_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    created_at: float = field(default_factory=time)
    future: asyncio.Future[bool] | None = None


@dataclass
class ResolvedApprovalRequest:
    request: ApprovalRequest
    approved: bool
    resolved_at: float = field(default_factory=time)


class ApprovalManager:
    def __init__(self):
        self._pending: dict[str, ApprovalRequest] = {}
        self._resolved: dict[str, ResolvedApprovalRequest] = {}

    def create(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        reason: str,
        turn_id: str | None = None,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            approval_request_id=uuid4().hex,
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
            future=asyncio.get_running_loop().create_future(),
        )
        self._pending[request.approval_request_id] = request
        return request

    def resolve(self, approval_request_id: str, approved: bool) -> ApprovalRequest:
        request = self._pending.get(approval_request_id)
        if request is None and approval_request_id in self._resolved:
            return self._resolved[approval_request_id].request
        if request is None:
            raise FileNotFoundError(f"Approval request not found: {approval_request_id}")
        self._remember_resolved(approval_request_id, request, approved)
        if request.future and not request.future.done():
            request.future.set_result(approved)
        return request

    def discard(self, approval_request_id: str, *, resolved_approved: bool | None = None) -> None:
        request = self._pending.pop(approval_request_id, None)
        if request and resolved_approved is not None and approval_request_id not in self._resolved:
            self._remember_resolved(approval_request_id, request, resolved_approved)
        if request and request.future and not request.future.done():
            request.future.cancel()

    def get(self, approval_request_id: str) -> ApprovalRequest:
        request = self._pending.get(approval_request_id)
        if request is None and approval_request_id in self._resolved:
            return self._resolved[approval_request_id].request
        if request is None:
            raise FileNotFoundError(f"Approval request not found: {approval_request_id}")
        return request

    def get_resolved(self, approval_request_id: str) -> ResolvedApprovalRequest | None:
        return self._resolved.get(approval_request_id)

    def list_pending(self) -> list[ApprovalRequest]:
        return sorted(
            (request for request_id, request in self._pending.items() if request_id not in self._resolved),
            key=lambda item: item.created_at,
        )

    def list_for_sessions(self, session_ids: list[str] | set[str] | tuple[str, ...]) -> list[ApprovalRequest]:
        allowed = set(session_ids)
        if not allowed:
            return []
        return [request for request in self.list_pending() if request.session_id in allowed]

    def find_for_session(self, session_id: str) -> ApprovalRequest | None:
        matches = [request for request in self.list_pending() if request.session_id == session_id]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return matches[0]

    async def wait(self, approval_request_id: str, timeout_seconds: int) -> bool:
        request = self.get(approval_request_id)
        if request.future is None:
            raise RuntimeError("Approval request is missing wait future")
        return await asyncio.wait_for(request.future, timeout=timeout_seconds)

    def _remember_resolved(self, approval_request_id: str, request: ApprovalRequest, approved: bool) -> None:
        self._resolved[approval_request_id] = ResolvedApprovalRequest(request=request, approved=approved)
        if len(self._resolved) <= MAX_RESOLVED_APPROVALS:
            return
        oldest_id = min(self._resolved, key=lambda item: self._resolved[item].resolved_at)
        self._resolved.pop(oldest_id, None)
