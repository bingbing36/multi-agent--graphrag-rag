from __future__ import annotations

import argparse
import json
import os
import sys

from config import DEFAULT_THREAD_ID, DEFAULT_USER_ID
from agents import get_app
from memory import build_config
from streaming import (
    inspect_thread_state,
    resume_thread,
    run,
    run_multi_round_dialogue,
    update_review_decision,
)


def classify_provider_error(exc: Exception) -> str | None:
    """识别模型余额异常来源"""
    text = str(exc).lower()
    if "insufficient balance" not in text and "quota" not in text:
        return None
    if "deepseek" in text or "api.deepseek.com" in text:
        return "DeepSeek 余额/额度不足，请充值 DeepSeek。"
    if "dashscope" in text or "aliyuncs" in text or "qwen" in text:
        return "Qwen 余额/额度不足，请充值阿里云百炼。"

    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    if provider == "qwen":
        return "Qwen 余额/额度不足，请充值阿里云百炼。"
    return "DeepSeek 余额/额度不足，请充值 DeepSeek。"


def classify_db_auth_error(exc: Exception) -> str | None:
    """识别图库/向量库认证错误"""
    text = str(exc).lower()
    if (
        "neo4j" in text
        and (
            "unauthorized" in text
            or "authentication failure" in text
            or "username and password are correct" in text
            or "security.unauthorized" in text
        )
    ):
        return "Neo4j 账号认证失败，请检查 NEO4J_USERNAME / NEO4J_PASSWORD。"

    if (
        "milvus" in text
        and (
            "unauthorized" in text
            or "authentication" in text
            or "permission denied" in text
            or "token" in text
        )
    ):
        return "Milvus 账号认证失败，请检查 MILVUS_USER / MILVUS_PASSWORD。"
    return None


def cli_main() -> None:
    """命令行主入口"""
    parser = argparse.ArgumentParser(
        description=(
            "Hybrid knowledge retrieval multi-agent system with streaming, memory, "
            "and human-in-the-loop support."
        )
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Question to send into the supervisor graph.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Run the graph with invoke() instead of streaming output.",
    )
    parser.add_argument(
        "--thread-id",
        default=DEFAULT_THREAD_ID,
        help="Thread id used by the short-term memory checkpointer.",
    )
    parser.add_argument(
        "--user-id",
        default=DEFAULT_USER_ID,
        help="User id used by the long-term memory store.",
    )
    parser.add_argument(
        "--stream-mode",
        choices=["values", "messages", "debug", "events", "invoke"],
        default="values",
        help="Streaming mode for LangGraph execution.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted thread without sending a new user message.",
    )
    parser.add_argument(
        "--inspect-state",
        action="store_true",
        help="Inspect the current thread state snapshot.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve the pending human review and resume the same thread.",
    )
    parser.add_argument(
        "--reject",
        action="store_true",
        help="Reject the pending human review and resume the same thread.",
    )
    parser.add_argument(
        "--review-note",
        default="",
        help="Optional note stored together with the human review decision.",
    )
    parser.add_argument(
        "--dialogue",
        action="store_true",
        help="Run interactive multi-round dialogue with built-in yes/no review prompts.",
    )
    args = parser.parse_args()

    if args.approve and args.reject:
        raise ValueError("Choose either --approve or --reject, not both.")

    stream_mode = "invoke" if args.no_stream else args.stream_mode

    if args.inspect_state:
        print(
            json.dumps(
                inspect_thread_state(thread_id=args.thread_id, user_id=args.user_id),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return

    if args.dialogue:
        graph = get_app()
        config = build_config(thread_id=args.thread_id, user_id=args.user_id)
        run_multi_round_dialogue(graph, config)
        return

    try:
        if args.approve or args.reject:
            decision = "approve" if args.approve else "reject"
            update_review_decision(
                decision,
                thread_id=args.thread_id,
                user_id=args.user_id,
                review_notes=args.review_note,
            )
            final_message = resume_thread(
                thread_id=args.thread_id,
                user_id=args.user_id,
                stream_mode=stream_mode,
            )
        elif args.resume:
            final_message = resume_thread(
                thread_id=args.thread_id,
                user_id=args.user_id,
                stream_mode=stream_mode,
            )
        else:
            question = " ".join(args.question).strip() or "List the companies in my database."
            final_message = run(
                question,
                thread_id=args.thread_id,
                user_id=args.user_id,
                stream_mode=stream_mode,
            )
    except Exception as exc:
        provider_error = classify_provider_error(exc)
        if provider_error:
            print(f"[ProviderError] {provider_error}", file=sys.stderr)
            raise SystemExit(2) from exc
        db_auth_error = classify_db_auth_error(exc)
        if db_auth_error:
            print(f"[DBAuthError] {db_auth_error}", file=sys.stderr)
            raise SystemExit(3) from exc
        raise

    if stream_mode == "invoke" and final_message is not None:
        print(final_message.content)


main = cli_main


if __name__ == "__main__":
    cli_main()
