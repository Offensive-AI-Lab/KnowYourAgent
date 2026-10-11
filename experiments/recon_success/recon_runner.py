"""
recon_runner.py — Runs KYA's recon agent, in isolation, against exactly one knowledge
asset for one AgentDojo case.

This reuses the exact same recon agent/task/tools classes KYA uses in production
(KYA/Recon/{agents,tasks,tools}.py + KYA/shared/flowAgentDojo.py's formatters) — it just
drives them directly with a fixed requirement id instead of letting a chosen strategy's
preconditions decide which requirements to collect. Each call builds a brand-new
AgentDojoChatSession and an empty target_profile, so requirements never see each other's
recon findings (see the plan's "isolated per requirement" decision).
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from benchmarks.agentdojo.src.api import AgentDojoChatSession
from kya.recon.agents import Recon
from kya.recon.tasks import Tasks as ReconTasks
from kya.tools import GetHistoryToolAgentDojo, InjectViaEnvironmentToolAgentDojo
from kya.flows.agentdojo import format_tactics, format_collected_information


def run_recon_for_requirement(
    case: dict,
    requirement_id: str,
    recon_model_name: str,
    target_model: str,
    defense_name: str | None,
    system_message_name: str | None,
    goal: str,
    context: str,
    strategies_dict: dict,
) -> tuple[str, AgentDojoChatSession]:
    """Run one isolated recon Task for one requirement. Returns (raw_output, session).

    The returned session is reused by ground_truth.py so ground truth is pulled from the
    exact same environment/system-prompt/defense the recon agent actually probed.
    """
    session = AgentDojoChatSession(
        suite_name=case["suite"],
        user_task_id=case["user_task"],
        model_name=target_model,
        injection_task_name=case["injection_task"],
        defense_name=defense_name,
        system_message_name=system_message_name,
    )

    get_history_tool = GetHistoryToolAgentDojo(session)
    inject_tool = InjectViaEnvironmentToolAgentDojo(session)
    recon_module = Recon(get_history_tool, inject_tool)

    recon_llm = ChatOpenAI(model_name=recon_model_name, temperature=0.7)
    recon_agent = recon_module.recon_agent_env(recon_llm)

    objective = str(strategies_dict["requirements"][requirement_id])
    tactics = format_tactics(strategies_dict["strategies"])
    collected_information = format_collected_information(
        {"collected_requirements": {}, "notes": " "}
    )

    task = ReconTasks.recon_task_env(
        recon_agent, objective, context, goal, tactics, collected_information
    )
    response = str(recon_agent.execute_task(task))

    return response, session
