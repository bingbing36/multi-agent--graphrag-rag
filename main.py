from __future__ import annotations

from agents import (
    AgentState,
    add_sale,
    chat,
    coder,
    delete_sale,
    get_app,
    get_coder_app,
    get_sqler_app,
    graph_kg,
    human_review,
    persist_memory,
    python_repl,
    query_sales,
    sqler,
    supervisor,
    update_sale,
    vec_kg,
)
from app import cli_main, main
from config import (
    APPROVAL_REQUIRED_MEMBERS,
    BASE_DIR,
    DATABASE_URI,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_THREAD_ID,
    DEFAULT_USER_ID,
    MEMORY_NODE,
    MEMBERS,
    PROJECT_ROOT,
    REVIEW_NODE,
)
from hitl import inspect_thread_state, update_review_decision
from memory import build_config, get_checkpointer, get_memory_store
from streaming import (
    astream_graph_events,
    invoke_once,
    run_dialogue,
    run_multi_round_dialogue,
    resume_thread,
    run,
    stream_debug,
    stream_messages,
    stream_values,
)

graph = get_app()
graph_with_memory = graph


if __name__ == "__main__":
    cli_main()
