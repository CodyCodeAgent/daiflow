"""Centralized session ID construction.

All DaiFlow business session IDs should be built through these helpers
to avoid string duplication and ensure consistency across modules.
"""


def task_plan(task_id: str) -> str:
    return f"task:{task_id}:plan"


def task_todo_split(task_id: str) -> str:
    return f"task:{task_id}:todo_split"


def task_todo_exec(task_id: str, todo_id: str) -> str:
    return f"task:{task_id}:todo:{todo_id}"


def task_review(task_id: str) -> str:
    return f"task:{task_id}:review"


def task_init_fetch(task_id: str) -> str:
    return f"task:{task_id}:init:fetch_code"


def task_init_skills(task_id: str) -> str:
    return f"task:{task_id}:init:sync_skills"


def task_init_commands(task_id: str) -> str:
    return f"task:{task_id}:init:sync_commands"


def task_init_bus(task_id: str) -> str:
    return f"task:init:{task_id}"


def task_spec(task_id: str) -> str:
    return f"task:{task_id}:spec"


def conversation_chat(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:chat"


def conversation_init_fetch(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:init:fetch_code"


def conversation_init_skills(conversation_id: str) -> str:
    return f"conversation:{conversation_id}:init:sync_skills"


def conversation_init_bus(conversation_id: str) -> str:
    return f"conversation:init:{conversation_id}"


def project_init(project_id: str, knowledge_type: str) -> str:
    return f"init:{project_id}:{knowledge_type}"


def project_init_bus(project_id: str) -> str:
    return f"project:init:{project_id}"
