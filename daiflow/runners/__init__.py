"""Agent runner implementations.

Each runner wraps a specific AI execution backend and exposes a unified
async streaming interface (AbstractAgentRunner protocol).

Runners yield DaiFlow event dicts directly — SessionRunner consumes them
without any backend-specific parsing.
"""

from daiflow.runners.base import AbstractAgentRunner

__all__ = ["AbstractAgentRunner"]
