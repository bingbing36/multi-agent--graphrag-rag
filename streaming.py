from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from langchain_core.messages import HumanMessage

from agents import get_app
from hitl import (
    inspect_thread_state as inspect_thread_state_with_app,
    is_review_pending,
    normalize_review_decision,
    print_pending_review_notice,
    update_review_decision as update_review_decision_with_app,
)
from memory import build_config, get_final_message_from_snapshot, get_last_message


def safe_print(text: str) -> None:
    """安全打印终端文本"""
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))


def inspect_thread_state(
    thread_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """查看线程状态"""
    return inspect_thread_state_with_app(get_app(), thread_id=thread_id, user_id=user_id)


def update_review_decision(
    decision: str,
    thread_id: str | None = None,
    user_id: str | None = None,
    review_notes: str = "",
) -> dict:
    """提交审核动作"""
    return update_review_decision_with_app(
        get_app(),
        decision,
        thread_id=thread_id,
        user_id=user_id,
        review_notes=review_notes,
    )


def build_payload(question: str | None, resume: bool) -> dict[str, list[HumanMessage]] | None:
    """构建输入载荷"""
    if resume:
        return None
    if not question:
        raise ValueError("question is required unless resume=True.")
    return {"messages": [HumanMessage(content=question)]}


def stream_values(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    resume: bool = False,
):
    """值模式流式运行"""
    app = get_app()
    config = build_config(thread_id=thread_id, user_id=user_id)
    payload = build_payload(question, resume=resume)
    final_message = None
    printed_messages: set[tuple[str | None, str]] = set()

    for step in app.stream(payload, config=config, stream_mode="values"):
        step_message = get_last_message(step.get("messages"))
        if step_message is None:
            continue
        final_message = step_message
        speaker = getattr(step_message, "name", "assistant")
        if not speaker:
            continue
        signature = (speaker, step_message.content)
        if signature in printed_messages:
            continue
        printed_messages.add(signature)
        safe_print(f"{speaker}: {step_message.content}")

    snapshot = app.get_state(config)
    if is_review_pending(snapshot):
        print_pending_review_notice(snapshot)
    return get_final_message_from_snapshot(snapshot) or final_message


def stream_messages(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    resume: bool = False,
):
    """消息模式流式运行"""
    app = get_app()
    config = build_config(thread_id=thread_id, user_id=user_id)
    payload = build_payload(question, resume=resume)

    for message_chunk, metadata in app.stream(payload, config=config, stream_mode="messages"):
        node_name = metadata.get("langgraph_node") or metadata.get("node") or "assistant"
        content = getattr(message_chunk, "content", "")
        tool_call_chunks = getattr(message_chunk, "tool_call_chunks", None)
        if content:
            safe_print(f"[{node_name}] {content}")
        if tool_call_chunks:
            safe_print(f"[{node_name}] tool_calls={tool_call_chunks}")

    snapshot = app.get_state(config)
    if is_review_pending(snapshot):
        print_pending_review_notice(snapshot)
    return get_final_message_from_snapshot(snapshot)


def stream_debug(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    resume: bool = False,
):
    """调试模式流式运行"""
    app = get_app()
    config = build_config(thread_id=thread_id, user_id=user_id)
    payload = build_payload(question, resume=resume)

    for chunk in app.stream(payload, config=config, stream_mode="debug"):
        print(json.dumps(chunk, ensure_ascii=False, default=str))

    snapshot = app.get_state(config)
    if is_review_pending(snapshot):
        print_pending_review_notice(snapshot)
    return get_final_message_from_snapshot(snapshot)


async def astream_graph_events(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    resume: bool = False,
    version: str = "v2",
):
    """异步输出事件流"""
    app = get_app()
    config = build_config(thread_id=thread_id, user_id=user_id)
    payload = build_payload(question, resume=resume)
    async for event in app.astream_events(payload, config=config, version=version):
        yield event


async def print_event_stream(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    resume: bool = False,
    version: str = "v2",
):
    """打印事件流数据"""
    async for event in astream_graph_events(
        question,
        thread_id=thread_id,
        user_id=user_id,
        resume=resume,
        version=version,
    ):
        simplified_event = {
            "event": event.get("event"),
            "name": event.get("name"),
            "metadata": event.get("metadata"),
            "data": event.get("data"),
        }
        print(json.dumps(simplified_event, ensure_ascii=False, default=str))


def invoke_once(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    resume: bool = False,
):
    """单次同步执行"""
    app = get_app()
    config = build_config(thread_id=thread_id, user_id=user_id)
    payload = build_payload(question, resume=resume)
    result = app.invoke(payload, config=config)
    snapshot = app.get_state(config)
    if is_review_pending(snapshot):
        print_pending_review_notice(snapshot)
    return get_final_message_from_snapshot(snapshot) or get_last_message(result.get("messages"))


def resume_thread(
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    stream_mode: str = "values",
):
    """恢复中断线程"""
    return run(
        None,
        thread_id=thread_id,
        user_id=user_id,
        stream_mode=stream_mode,
        resume=True,
    )


def run(
    question: str | None = None,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    stream_mode: str = "values",
    resume: bool = False,
):
    """统一运行入口"""
    if stream_mode == "invoke":
        return invoke_once(
            question,
            thread_id=thread_id,
            user_id=user_id,
            resume=resume,
        )
    if stream_mode == "values":
        return stream_values(
            question,
            thread_id=thread_id,
            user_id=user_id,
            resume=resume,
        )
    if stream_mode == "messages":
        return stream_messages(
            question,
            thread_id=thread_id,
            user_id=user_id,
            resume=resume,
        )
    if stream_mode == "debug":
        return stream_debug(
            question,
            thread_id=thread_id,
            user_id=user_id,
            resume=resume,
        )
    if stream_mode == "events":
        asyncio.run(
            print_event_stream(
                question,
                thread_id=thread_id,
                user_id=user_id,
                resume=resume,
            )
        )
        app = get_app()
        snapshot = app.get_state(build_config(thread_id=thread_id, user_id=user_id))
        return get_final_message_from_snapshot(snapshot)
    raise ValueError("stream_mode must be one of: values, messages, debug, events, invoke.")


def run_dialogue(
    graph=None,
    config: dict[str, Any] | None = None,
    all_chunks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """运行人工审批对话"""
    if graph is None:
        graph = get_app()
    if config is None:
        config = build_config()
    if all_chunks is None:
        all_chunks = []

    while True:
        user_input = input("请输入您的消息（输入'退出'结束对话）：").strip()
        if user_input.lower() == "退出":
            break

        for chunk in graph.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config,
            stream_mode="values",
        ):
            all_chunks.append(chunk)

        snapshot = graph.get_state(config)
        if is_review_pending(snapshot):
            state_values = getattr(snapshot, "values", {}) or {}
            approval_request = state_values.get("approval_request") or (
                f"用户输入的指令是:{user_input}, 请人工确认是否执行！"
            )
            user_approval = input(f"{approval_request}\n请回复 是/否：").strip()
            yes_values = {"是", "yes", "y", "true", "1", "同意", "通过"}
            decision = "approve" if user_approval.lower() in yes_values else "reject"
            update_review_decision_with_app(
                graph,
                decision,
                thread_id=config.get("configurable", {}).get("thread_id"),
                user_id=config.get("configurable", {}).get("user_id"),
                review_notes=f"manual input: {user_approval}",
            )

            for chunk in graph.stream(None, config, stream_mode="values"):
                all_chunks.append(chunk)

        if all_chunks:
            final_message = get_last_message(all_chunks[-1].get("messages"))
            if final_message is not None:
                print("人工智能助理：", final_message.content)

    return all_chunks


def _ask_yes_no(prompt: str) -> str:
    """循环询问直到输入是或否"""
    while True:
        user_input = input(prompt).strip()
        decision = normalize_review_decision(user_input)
        if decision in {"approve", "reject"}:
            return decision
        print("输入无效，请输入“是”或“否”。")


def run_multi_round_dialogue(graph=None, config: dict[str, Any] | None = None) -> None:
    """多轮对话 + 人机审核流程"""
    if graph is None:
        graph = get_app()
    if config is None:
        config = build_config()

    while True:
        user_input = input("请输入您的问题（输入'退出'结束对话）：").strip()
        if user_input.lower() == "退出":
            print("对话已结束。")
            break
        if not user_input:
            print("输入为空，请重新输入。")
            continue

        last_reply = None
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config,
            stream_mode="values",
        ):
            reply = get_last_message(chunk.get("messages"))
            if reply is not None:
                last_reply = reply

        snapshot = graph.get_state(config)
        if is_review_pending(snapshot):
            values = getattr(snapshot, "values", {}) or {}
            approval_request = values.get("approval_request") or (
                f"用户输入的指令是: {user_input}，请人工确认是否执行。"
            )
            decision = _ask_yes_no(f"{approval_request}\n请输入“是”或“否”：")
            update_review_decision_with_app(
                graph,
                decision,
                thread_id=config.get("configurable", {}).get("thread_id"),
                user_id=config.get("configurable", {}).get("user_id"),
                review_notes=f"manual decision: {decision}",
            )
            for chunk in graph.stream(None, config, stream_mode="values"):
                reply = get_last_message(chunk.get("messages"))
                if reply is not None:
                    last_reply = reply

        if last_reply is not None:
            print(f"人工智能助理：{last_reply.content}")
