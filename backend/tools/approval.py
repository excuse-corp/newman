from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


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


class ApprovalManager:
    def __init__(self):
        self._pending: dict[str, ApprovalRequest] = {}

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
        if request is None:
            raise FileNotFoundError(f"Approval request not found: {approval_request_id}")
        if request.future and not request.future.done():
            request.future.set_result(approved)
        return request

    def discard(self, approval_request_id: str) -> None:
        request = self._pending.pop(approval_request_id, None)
        if request and request.future and not request.future.done():
            request.future.cancel()

    def get(self, approval_request_id: str) -> ApprovalRequest:
        request = self._pending.get(approval_request_id)
        if request is None:
            raise FileNotFoundError(f"Approval request not found: {approval_request_id}")
        return request

    def find_for_session(self, session_id: str) -> ApprovalRequest | None:
        matches = [request for request in self._pending.values() if request.session_id == session_id]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at, reverse=True)
        return matches[0]

    async def wait(self, approval_request_id: str, timeout_seconds: int) -> bool:
        request = self.get(approval_request_id)
        if request.future is None:
            raise RuntimeError("Approval request is missing wait future")
        return await asyncio.wait_for(request.future, timeout=timeout_seconds)
