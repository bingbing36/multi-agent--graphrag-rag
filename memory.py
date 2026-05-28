from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from config import DEFAULT_MEMORY_LIMIT, DEFAULT_THREAD_ID, DEFAULT_USER_ID


def build_config(thread_id: str | None = None, user_id: str | None = None) -> dict[str, dict[str, str]]:
    """组装线程配置"""
    return {
        "configurable": {
            "thread_id": thread_id or DEFAULT_THREAD_ID,
            "user_id": user_id or DEFAULT_USER_ID,
        }
    }


@lru_cache(maxsize=1)
def get_checkpointer() -> MemorySaver:
    """获取短期记忆器"""
    return MemorySaver()


@lru_cache(maxsize=1)
def get_memory_store() -> InMemoryStore:
    """获取长期记忆库"""
    return InMemoryStore()


def get_memory_namespace(config: RunnableConfig | None) -> tuple[str, str]:
    """生成记忆命名空间"""
    configurable = {}
    if config is not None:
        configurable = dict(config.get("configurable", {}))
    user_id = str(configurable.get("user_id") or DEFAULT_USER_ID)
    return ("memories", user_id)


def extract_memory_text(record: Any) -> str:
    """解析记忆文本"""
    value = getattr(record, "value", record)
    if isinstance(value, dict):
        memory_text = value.get("data") or value.get("text")
        if memory_text:
            return str(memory_text)
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def get_long_term_memories(
    config: RunnableConfig | None,
    store: BaseStore | None,
    limit: int = DEFAULT_MEMORY_LIMIT,
) -> list[str]:
    """读取长期记忆"""
    if store is None:
        return []
    records = list(store.search(get_memory_namespace(config)))
    if not records:
        return []
    return [extract_memory_text(record) for record in records[-limit:]]


def build_memory_system_message(
    config: RunnableConfig | None,
    store: BaseStore | None,
    limit: int = DEFAULT_MEMORY_LIMIT,
) -> SystemMessage | None:
    """构造记忆提示词"""
    memories = get_long_term_memories(config, store, limit=limit)
    if not memories:
        return None
    memory_text = "\n".join(f"- {memory}" for memory in memories)
    return SystemMessage(
        content=(
            "Below are durable cross-thread memories about this user. "
            "Use them only when relevant to the current request.\n"
            f"{memory_text}"
        )
    )


def with_memory_context(
    messages: Sequence[BaseMessage],
    config: RunnableConfig | None,
    store: BaseStore | None,
) -> list[BaseMessage]:
    """注入记忆上下文"""
    prepared_messages = list(messages)
    memory_message = build_memory_system_message(config, store)
    if memory_message is None:
        return prepared_messages
    return [memory_message, *prepared_messages]


def get_latest_user_message(messages: Sequence[BaseMessage]) -> str | None:
    """获取最近用户消息"""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not getattr(message, "name", None):
            return str(message.content)
    return None


def build_knowledge_question(
    question: str,
    config: RunnableConfig | None,
    store: BaseStore | None,
) -> str:
    """拼接知识库问题"""
    memories = get_long_term_memories(config, store)
    if not memories:
        return question
    memory_text = "\n".join(f"- {memory}" for memory in memories)
    return (
        "Relevant cross-thread user memory:\n"
        f"{memory_text}\n\n"
        "Current question:\n"
        f"{question}"
    )


def get_last_message(messages: Sequence[BaseMessage] | None) -> BaseMessage | None:
    """获取最后一条消息"""
    if not messages:
        return None
    return messages[-1]


def get_final_message_from_snapshot(snapshot: Any) -> BaseMessage | None:
    """提取快照最终消息"""
    values = getattr(snapshot, "values", {}) or {}
    return get_last_message(values.get("messages"))
