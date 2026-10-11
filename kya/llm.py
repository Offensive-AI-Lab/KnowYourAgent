"""LLM configuration for the KYA crew (Recon, Attacker, Planner, Evaluator).

Each role can run on its own model. ``PRESETS`` holds the per-benchmark role
assignments used for the paper's experiments; ``--model`` on any entry point
overrides every role at once, and ``--<role>-model`` overrides a single role.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace

# gpt-5-family models reject non-default sampling parameters; let LiteLLM drop them
# instead of failing the request (the paper runs exported the same setting).
os.environ.setdefault("LITELLM_DROP_PARAMS", "True")

from crewai import LLM  # noqa: E402

TEMPERATURE = 0.7
EVALUATOR_TEMPERATURE = 1.0


@dataclass(frozen=True)
class CrewModels:
    """Model name per KYA role."""
    recon: str
    execution_planner: str
    payload_designer: str
    planner: str
    evaluator: str

    @classmethod
    def uniform(cls, model: str) -> "CrewModels":
        return cls(**{f.name: model for f in fields(cls)})

    def llm(self, role: str) -> LLM:
        temperature = EVALUATOR_TEMPERATURE if role == "evaluator" else TEMPERATURE
        return LLM(model=getattr(self, role), temperature=temperature)


ROLES = [f.name for f in fields(CrewModels)]

PRESETS = {
    "agentdojo": CrewModels(
        recon="gpt-5",
        execution_planner="gpt-5.1",
        payload_designer="gpt-4o",
        planner="gpt-4o",
        evaluator="gpt-4o",
    ),
    "injecagent": CrewModels.uniform("gpt-4o"),
    "openhands": CrewModels.uniform("gpt-5.1"),
}


def add_model_arguments(parser) -> None:
    """Register ``--model`` and the per-role ``--<role>-model`` flags on an argparse parser."""
    parser.add_argument(
        "-m", "--model", default=None,
        help="Run every KYA role on this model (overrides the benchmark preset).",
    )
    for role in ROLES:
        parser.add_argument(
            f"--{role.replace('_', '-')}-model", default=None,
            help=f"Model for the {role.replace('_', ' ')} role only.",
        )


def models_from_args(args, benchmark: str) -> CrewModels:
    """Resolve the crew models: preset -> ``--model`` -> per-role flags."""
    models = CrewModels.uniform(args.model) if args.model else PRESETS[benchmark]
    overrides = {role: getattr(args, f"{role}_model") for role in ROLES if getattr(args, f"{role}_model")}
    return replace(models, **overrides)
