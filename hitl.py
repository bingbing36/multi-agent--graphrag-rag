from __future__ import annotations

from typing import Any

from config import DEFAULT_THREAD_ID, DEFAULT_USER_ID, REVIEW_NODE
from memory import build_config


def normalize_review_decision(decision: str | None) -> str | None:
    """标准化审核动作"""
    if not decision:
        return None
    normalized = decision.strip().lower().replace("\u3000", " ")
    if normalized in {"approve", "approved", "yes", "y", "true", "1", "是", "同意", "通过"}:
        return "approve"
    if normalized in {"reject", "rejected", "no", "n", "false", "0", "否", "拒绝", "驳回"}:
        return "reject"
    return None


def is_review_pending(snapshot: Any) -> bool:
    """判断是否待审核"""
    pending_nodes = tuple(getattr(snapshot, "next", ()) or ())
    return REVIEW_NODE in pending_nodes


def summarize_state_snapshot(snapshot: Any) -> dict[str, Any]:
    """汇总状态快照"""
    values = getattr(snapshot, "values", {}) or {}
    messages = values.get("messages", []) or []
    latest_message = messages[-1] if messages else None
    return {
        "next": list(getattr(snapshot, "next", ()) or ()),
        "message_count": len(messages),
        "latest_message": getattr(latest_message, "content", None),
        "approval_request": values.get("approval_request"),
        "pending_worker": values.get("pending_worker"),
        "review_decision": values.get("review_decision"),
        "review_notes": values.get("review_notes"),
    }


def get_thread_state_snapshot(
    app,
    thread_id: str | None = None,
    user_id: str | None = None,
):
    """读取线程状态"""
    return app.get_state(build_config(thread_id=thread_id, user_id=user_id))


def inspect_thread_state(
    app,
    thread_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """查看线程详情"""
    snapshot = get_thread_state_snapshot(app, thread_id=thread_id, user_id=user_id)
    summary = summarize_state_snapshot(snapshot)
    summary["thread_id"] = thread_id or DEFAULT_THREAD_ID
    summary["user_id"] = user_id or DEFAULT_USER_ID
    return summary


def update_review_decision(
    app,
    decision: str,
    thread_id: str | None = None,
    user_id: str | None = None,
    review_notes: str = "",
) -> dict[str, Any]:
    """更新审核决策"""
    normalized = normalize_review_decision(decision)
    if normalized is None:
        raise ValueError("review decision must be approve or reject.")
    config = build_config(thread_id=thread_id, user_id=user_id)
    app.update_state(
        config,
        {
            "review_decision": normalized,
            "review_notes": review_notes,
        },
    )
    return inspect_thread_state(app, thread_id=thread_id, user_id=user_id)


def print_pending_review_notice(snapshot: Any) -> None:
    """打印审核提示"""
    summary = summarize_state_snapshot(snapshot)
    approval_request = summary.get("approval_request") or "Current thread is waiting for human review."
    print(f"[human_review] {approval_request}")
    print("Use the same --thread-id with --approve or --reject to resume this thread.")
