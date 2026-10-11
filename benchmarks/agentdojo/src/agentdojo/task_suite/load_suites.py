from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentdojo.task_suite.task_suite import TaskSuite

_SUITES: defaultdict[str, dict[str, TaskSuite]] = defaultdict(dict)
_suites_initialized = False


def _init_suites() -> None:
    """Lazily initialize all suites to avoid circular imports.

    The v1 suites must be fully loaded before the versioned suites (v1_1,
    v1_1_1, …) because the latter import symbols defined by the former.
    Deferring everything to first-use breaks the import cycle that previously
    occurred when ``task_suite/__init__.py`` eagerly imported this module.
    """
    global _suites_initialized
    if _suites_initialized:
        return
    _suites_initialized = True

    # --- v1 suites (must come first) ---
    from agentdojo.default_suites.v1.banking import banking_task_suite
    from agentdojo.default_suites.v1.slack import slack_task_suite
    from agentdojo.default_suites.v1.travel import travel_task_suite
    from agentdojo.default_suites.v1.workspace import workspace_task_suite

    # --- versioned suite registrations (depend on v1 being loaded) ---
    import agentdojo.default_suites.v1_1  # Register new tasks
    import agentdojo.default_suites.v1_1_1  # Register new tasks
    import agentdojo.default_suites.v1_2  # Register new tasks
    import agentdojo.default_suites.v1_2_1  # noqa: F401 # Register new tasks

    _SUITES.update(
        {
            "v1": {
                "workspace": workspace_task_suite,
                "travel": travel_task_suite,
                "banking": banking_task_suite,
                "slack": slack_task_suite,
            },
            "v1.1": {
                "workspace": workspace_task_suite,
                "travel": travel_task_suite.get_new_version((1, 1, 0)),
                "banking": banking_task_suite,
                "slack": slack_task_suite,
            },
            "v1.1.1": {
                "workspace": workspace_task_suite.get_new_version((1, 1, 1)),
                "travel": travel_task_suite.get_new_version((1, 1, 1)),
                "banking": banking_task_suite.get_new_version((1, 1, 1)),
                "slack": slack_task_suite.get_new_version((1, 1, 1)),
            },
            "v1.1.2": {
                "workspace": workspace_task_suite.get_new_version((1, 1, 2)),
                "travel": travel_task_suite.get_new_version((1, 1, 2)),
                "banking": banking_task_suite.get_new_version((1, 1, 1)),
                "slack": slack_task_suite.get_new_version((1, 1, 1)),
            },
            "v1.2": {
                "workspace": workspace_task_suite.get_new_version((1, 2, 0)),
                "travel": travel_task_suite.get_new_version((1, 2, 0)),
                "banking": banking_task_suite.get_new_version((1, 2, 0)),
                "slack": slack_task_suite.get_new_version((1, 2, 0)),
            },
            "v1.2.1": {
                "workspace": workspace_task_suite.get_new_version((1, 2, 1)),
                "travel": travel_task_suite.get_new_version((1, 2, 0)),
                "banking": banking_task_suite.get_new_version((1, 2, 0)),
                "slack": slack_task_suite.get_new_version((1, 2, 0)),
            },
        }
    )


def register_suite(suite: TaskSuite, version: str) -> None:
    _init_suites()
    _SUITES[version][suite.name] = suite


def get_suites(benchmark_version: str) -> dict[str, TaskSuite]:
    _init_suites()
    return _SUITES[benchmark_version]


def get_suite(benchmark_version: str, suite_name: str) -> TaskSuite:
    _init_suites()
    return _SUITES[benchmark_version][suite_name]
