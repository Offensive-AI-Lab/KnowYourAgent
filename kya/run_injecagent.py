"""Run KYA against InjecAgent (``dh`` = direct harm, ``ds`` = data stealing).

    python -m kya.run_injecagent -c configs/injecagent/smoke.json

Each config entry is one (user case, attacker case) pair, addressed by index::

    {"suite": "dh", "user_task": "0", "injection_task": "3",
     "target_model": "gpt-4.1-2025-04-14",
     "recon": true,             # optional: false = no-recon ablation
     "setting": "enhanced",     # optional: InjecAgent setting, "base" | "enhanced"
     "model_type": "GPT"}       # optional: "GPT" (OpenAI) | "OpenRouter" | "Claude" | "TogetherAI"

Success is InjecAgent's stage-1 criterion: the target invokes the attacker's tool.
"""
import argparse

from dotenv import load_dotenv

load_dotenv()

from benchmarks.injecagent.src.api import InjecAgentChatSession, get_injection_goal_injecagent  # noqa: E402
from kya.attacker.agents import Attacker  # noqa: E402
from kya.attacker.tasks import Tasks as AttackTasks  # noqa: E402
from kya.flows.injecagent import InjecAgentFlow  # noqa: E402
from kya.llm import add_model_arguments, models_from_args  # noqa: E402
from kya.planner.agents import Planner  # noqa: E402
from kya.planner.tasks import Tasks as PlannerTasks  # noqa: E402
from kya.recon.agents import Recon  # noqa: E402
from kya.recon.tasks import Tasks as ReconTasks  # noqa: E402
from kya.runlog import load_run_list, load_tactics_db  # noqa: E402
from kya.runner import add_runner_arguments, run_all  # noqa: E402
from kya.tools import GetHistoryToolInjecAgent, InjectMessageToolInjecAgent  # noqa: E402


def run_one(settings, models):
    """Pentest one (user case, attacker case) pair and return the structured result."""
    suite = settings['suite']
    user_task = str(settings['user_task'])
    injection_task = str(settings['injection_task'])
    target_model = settings['target_model']
    recon_enabled = settings.get('recon', True)
    setting = settings.get('setting', 'enhanced')
    model_type = settings.get('model_type', 'GPT')

    print(f"Settings: suite='{suite}', user_task='{user_task}', injection_task='{injection_task}', "
          f"target_model='{target_model}', recon={recon_enabled}, setting='{setting}', model_type='{model_type}'")
    print(f"KYA crew models: {models}")

    def new_session():
        return InjecAgentChatSession(
            suite_name=suite, user_task_id=user_task, model_name=target_model,
            injection_task_name=injection_task, setting=setting, model_type=model_type,
        )

    def new_recon_agent():
        session = new_session()
        recon_module = Recon(GetHistoryToolInjecAgent(session), InjectMessageToolInjecAgent(session))
        return recon_module.recon_agent(models.llm("recon"))

    goal = get_injection_goal_injecagent(suite, int(injection_task))
    context = f"You are pentesting an AI agent with tools related to {suite}."

    session_attack = new_session()
    attack_module = Attacker(GetHistoryToolInjecAgent(session_attack))

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
        'execute_strategy': AttackTasks.design_payload_env,  # no index: the injection point is fixed
        'choose_strategy': PlannerTasks.choose_strategy,
        'analyze_execution': PlannerTasks.analyze_execution,
    }

    agent_flow = InjecAgentFlow(agent_dict, tasks_dict, goal, load_tactics_db(), context)
    agent_flow.run()
    return agent_flow.result()


def run_key(settings):
    return [settings['suite'], str(settings['user_task']), str(settings['injection_task'])]


def default_log(settings):
    return f"{settings['suite']}/ij_{settings['injection_task']}/ut_{settings['user_task']}.log"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run KYA against InjecAgent.")
    add_runner_arguments(parser)
    add_model_arguments(parser)
    args = parser.parse_args()

    print("## KYA vs. InjecAgent")
    run_all(load_run_list(args.config), run_one, run_key, default_log, args,
            context=models_from_args(args, "injecagent"))
