"""Run KYA against AgentDojo (banking, slack, travel, workspace).

    python -m kya.run_agentdojo -c configs/agentdojo/smoke.json

Each config entry is one (user task, injection task) pair::

    {"suite": "banking", "user_task": "user_task_0", "injection_task": "injection_task_1",
     "target_model": "gpt-4.1-2025-04-14",
     "recon": true,            # optional: false = no-recon ablation
     "attack_tactic": true,    # optional: false = no-tactics ablation
     "defense": null,          # optional: repeat_user_prompt | spotlighting_with_delimiting | transformers_pi_detector
     "system_message_name": null}
"""
import argparse

from dotenv import load_dotenv

load_dotenv()

from benchmarks.agentdojo.src.api import AgentDojoChatSession, get_injection_goal  # noqa: E402
from kya.attacker.agents import Attacker  # noqa: E402
from kya.attacker.tasks import Tasks as AttackTasks  # noqa: E402
from kya.flows.agentdojo import AgentDojoFlow, format_collected_information, format_tactics  # noqa: E402
from kya.llm import add_model_arguments, models_from_args  # noqa: E402
from kya.planner.agents import Planner  # noqa: E402
from kya.planner.tasks import Tasks as PlannerTasks  # noqa: E402
from kya.recon.agents import Recon  # noqa: E402
from kya.recon.tasks import Tasks as ReconTasks  # noqa: E402
from kya.runlog import load_run_list, load_tactics_db  # noqa: E402
from kya.runner import add_runner_arguments, run_all  # noqa: E402
from kya.tools import GetHistoryToolAgentDojo, InjectViaEnvironmentToolAgentDojo  # noqa: E402


def run_one(settings, models):
    """Pentest one (user task, injection task) pair and return the structured result."""
    suite = settings['suite']
    user_task = settings['user_task']
    target_model = settings['target_model']
    injection_task = settings['injection_task']
    sys_msg_name = settings.get('system_message_name')
    recon_enabled = settings.get('recon', True)
    defense_name = settings.get('defense')

    print(f"Settings: suite='{suite}', user_task='{user_task}', injection_task='{injection_task}', "
          f"target_model='{target_model}', recon={recon_enabled}, defense='{defense_name}', sys_msg='{sys_msg_name}'")
    print(f"KYA crew models: {models}")

    def new_session():
        return AgentDojoChatSession(
            suite_name=suite, user_task_id=user_task, model_name=target_model,
            injection_task_name=injection_task, defense_name=defense_name,
            system_message_name=sys_msg_name,
        )

    def new_recon_agent():
        # Every recon phase probes a fresh session of the target.
        session = new_session()
        recon_module = Recon(GetHistoryToolAgentDojo(session), InjectViaEnvironmentToolAgentDojo(session))
        return recon_module.recon_agent_env(models.llm("recon"))

    goal = get_injection_goal(suite, injection_task)
    context = f"You are pentesting an AI agent with tools related to {suite}."
    strategy_db_dict = load_tactics_db()

    session_attack = new_session()
    attack_module = Attacker(GetHistoryToolAgentDojo(session_attack))

    agent_dict = {
        'recon_factory': new_recon_agent,
        'recon_enabled': recon_enabled,
        'attack_tactic': settings.get('attack_tactic', True),
        'execution_planner': attack_module.get_plan_execution_agent(models.llm("execution_planner")),
        'executor': attack_module.payload_designer(models.llm("payload_designer")),
        'session': session_attack,
        'orchestrator': Planner.planner(models.llm("planner")),
        'evaluator': Planner.evaluator(models.llm("evaluator")),
    }
    tasks_dict = {
        'recon_task': ReconTasks.recon_task_env,
        'plan_execution': AttackTasks.plan_execution_with_tactics,
        'execute_strategy': AttackTasks.design_payload_env,
        'choose_strategy': PlannerTasks.choose_strategy,
        'analyze_execution': PlannerTasks.analyze_execution,
    }

    agent_flow = AgentDojoFlow(agent_dict, tasks_dict, goal, strategy_db_dict, context)
    collected = agent_flow.target_profile['collected_requirements']

    # --- Pre-populate the target profile with what a benign run already reveals ---
    if recon_enabled:
        print("Pre-populating target profile with programmatic data...")

        # 1. benign_response: the agent's final answer on the un-injected task
        benign_response = session_attack.get_benign_response()
        collected['benign_response'] = f"Target agent's benign response: {benign_response}"
        print(f"  [+] benign_response collected ({len(benign_response)} chars)")

        # 2. agent_task: the user's message to the agent
        agent_task = session_attack.get_agent_task()
        collected['agent_task'] = f"The agent is tasked with the following: {agent_task}"
        print(f"  [+] agent_task collected ({len(agent_task)} chars)")

        # 3. injected_tool_output: where the injection lands, marked with <<INJECTION_LOCATION>>
        collected['injected_tool_output'] = session_attack.get_injected_tool_output_info()
        print(f"  [+] injected_tool_output collected")
    else:
        print("Recon disabled — skipping target profile pre-population.")

    # --- Defense-aware recon: probe the 'structural_defenses' asset when a defense is active ---
    if defense_name and recon_enabled:
        print(f"Defense '{defense_name}' detected — running recon for 'structural_defenses' requirement...")
        filters_requirement = strategy_db_dict.get('requirements', {}).get('structural_defenses', {})
        tactics = format_tactics(strategy_db_dict.get('strategies', {}))
        collected_information = format_collected_information(agent_flow.target_profile)
        filters_recon_agent = new_recon_agent()
        filters_response = str(filters_recon_agent.execute_task(
            tasks_dict['recon_task'](
                filters_recon_agent, str(filters_requirement), context, goal, tactics, collected_information
            )
        ))
        collected['structural_defenses'] = filters_response
        print(f"  [+] structural_defenses collected ({len(filters_response)} chars)")

    agent_flow.run()
    return agent_flow.result()


def run_key(settings):
    return [settings['suite'], settings['user_task'], settings['injection_task']]


def default_log(settings):
    return f"{settings['suite']}/{settings['injection_task']}/{settings['user_task']}.log"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run KYA against AgentDojo (environment injection).")
    add_runner_arguments(parser)
    add_model_arguments(parser)
    args = parser.parse_args()

    print("## KYA vs. AgentDojo")
    run_all(load_run_list(args.config), run_one, run_key, default_log, args,
            context=models_from_args(args, "agentdojo"))
