"""
AgentVigil - MCTS-Based Black-Box Fuzzing Framework for AI Agent Red Teaming

A comprehensive framework for finding indirect prompt injection vulnerabilities
in AI agents using Monte Carlo Tree Search (MCTS) to iteratively refine and 
mutate attack prompts.

Key Components:
- agentvigil.py: Core MCTS engine and node management
- flowAgentDojoAgentVigil.py: Integration with AgentDojo
- flowAgentVigil.py: Main orchestration flows
- agents.py: CrewAI agent definitions
- tasks.py: CrewAI task definitions
"""

from .agentvigil import (
    MCTSNode,
    Mutator,
    LLMMutator,
    TargetInterface,
    Evaluator,
    AgentVigilMCTS,
    AgentVigilTemplateMCTS,
    MutationStrategy,
)

from .flowAgentDojoAgentVigil import (
    AgentDojoTargetInterface,
    AgentDojoTemplateTarget,
    AgentVigilAgentDojo,
)

from .flowAgentVigil import (
    AgentVigilFlow,
    AgentVigilFlowMCTS,
)

__version__ = "1.0.0"
__all__ = [
    "MCTSNode",
    "Mutator",
    "LLMMutator",
    "TargetInterface",
    "Evaluator",
    "AgentVigilMCTS",
    "AgentVigilTemplateMCTS",
    "MutationStrategy",
    "AgentDojoTargetInterface",
    "AgentDojoTemplateTarget",
    "AgentVigilAgentDojo",
    "AgentVigilFlow",
    "AgentVigilFlowMCTS",
]
