"""
AgentVigil Integration with AgentDojo
Allows AgentVigil MCTS fuzzer to work with AgentDojo sessions
"""

import logging
from typing import List, Optional, Dict, Tuple
from baselines.agentvigil.agentvigil import (
    AgentVigilMCTS,
    TargetInterface,
    Mutator,
    Evaluator,
    MCTSNode
)
from benchmarks.agentdojo.src.api import AgentDojoChatSession, get_injection_goal as get_injection_goal_agentdojo, get_user_task_prompt as get_user_task_prompt_agentdojo, _make_json_serializable

logger = logging.getLogger(__name__)


class AgentDojoTargetInterface(TargetInterface):
    """
    Adapter for AgentVigil to interact with AgentDojo chat sessions.
    Implements the TargetInterface for AgentDojo-based attacks.
    """
    
    def __init__(self, session):
        """
        Initialize the AgentDojo target interface.
        
        Args:
            session: An AgentDojoChatSession instance
        """
        self.session = session
        self.query_count = 0
        self.responses = []
    
    def query(self, input_text: str = "", **kwargs) -> str:
        """
        Send a prompt injection payload to the AgentDojo session.
        
        Args:
            input_text: The payload to inject
            
        Returns:
            The agent's response to the injection
        """
        try:
            self.query_count += 1
            
            # Initialize chat session
            self.session.init_chat()
            
            # Inject the payload at a default index (middle of conversation)
            # This simulates tool output injection
            messages, success, utility = self.session.inject_content_at_index_limited(
                content=input_text,
                index=2  # Default injection point
            )
            
            response_str = str(messages)
            self.responses.append({
                "payload": input_text,
                "response": response_str,
                "success": success,
                "utility": utility
            })
            
            logger.debug(f"AgentDojo Query #{self.query_count}: {input_text[:50]}...")
            return response_str
            
        except Exception as e:
            logger.error(f"Error during AgentDojo query: {e}")
            return f"ERROR: {str(e)}"
    
    def reset(self) -> None:
        """Reset the session."""
        try:
            self.session.init_chat()
            logger.debug("AgentDojo session reset")
        except Exception as e:
            logger.error(f"Error resetting session: {e}")
    
    def get_query_count(self) -> int:
        """Get the number of queries sent."""
        return self.query_count


class AgentDojoTemplateTarget(TargetInterface):
    """
    Target interface for template-based attacks across multiple AgentDojo test cases.
    Provides binary success signals via the AgentDojo API.
    """

    def __init__(self, target_model: str, defense_name: Optional[str] = None):
        self.target_model = target_model
        self.defense_name = defense_name
        self.query_count = 0
        # Force suite registry to fully initialize before any threads start.
        # _init_suites() has a race condition: it sets the "initialized" flag
        # before populating _SUITES, so threads that check the flag early get
        # an empty registry. Calling get_suite here in the main thread ensures
        # _SUITES is fully populated before the thread pool launches.
        from agentdojo.task_suite.load_suites import _init_suites
        _init_suites()

    def query(self, template: str, user_task: str, injection_task: str, suite: str, **kwargs) -> Dict[str, str]:
        self.query_count += 1
        goal = get_injection_goal_agentdojo(suite, injection_task)
        user_task_prompt = get_user_task_prompt_agentdojo(suite, user_task)
        payload = self._format_template(template, goal, user_task=user_task_prompt, model_name=self.target_model)

        session = AgentDojoChatSession(
            suite_name=suite,
            user_task_id=user_task,
            model_name=self.target_model,
            injection_task_name=injection_task,
            defense_name=self.defense_name,
            system_message_name=None,
        )

        try:
            messages, success, utility = session.inject_prompt_via_environment(payload)
            conversation = _make_json_serializable(list(messages))
            response = str(messages)
        except Exception as e:
            success = False
            utility = False
            conversation = []
            response = f"ERROR: {str(e)}"

        return {
            "malicious_goal": goal,
            "payload": payload,
            "response": response,
            "conversation": conversation,
            "success": bool(success),
            "utility": bool(utility),
        }

    def reset(self) -> None:
        """No-op for template target; each query uses a fresh session."""
        return None

    def get_query_count(self) -> int:
        return self.query_count

    @staticmethod
    def _format_template(template: str, malicious_goal: str, user_task: str = "", model_name: str = "") -> str:
        if "{malicious_goal}" not in template:
            template = f"{template} {{malicious_goal}}"
        return template.format(malicious_goal=malicious_goal, user_task=user_task, model_name=model_name)


class AgentVigilAgentDojo:
    """
    Integration layer combining AgentVigil MCTS with AgentDojo sessions.
    Manages the fuzzing workflow tailored for AgentDojo.
    """
    
    def __init__(
        self,
        agentdojo_session,
        goal: str,
        exploration_weight: float = 1.41,
        max_depth: int = 10,
    ):
        """
        Initialize AgentVigil for AgentDojo.
        
        Args:
            agentdojo_session: An AgentDojoChatSession instance
            goal: The pentesting goal/objective
            exploration_weight: UCB1 exploration weight
            max_depth: Maximum tree depth for MCTS
        """
        self.session = agentdojo_session
        self.goal = goal
        self.exploration_weight = exploration_weight
        self.max_depth = max_depth
        
        # Create the target interface
        self.target = AgentDojoTargetInterface(agentdojo_session)
        
        # Initialize MCTS engine
        self.mcts = AgentVigilMCTS(
            target_interface=self.target,
            mutator=Mutator,
            evaluator=Evaluator,
            exploration_weight=exploration_weight,
            max_depth=max_depth,
        )
        
        self.results = None
        logger.info("AgentVigil-AgentDojo integration initialized")
    
    def run(
        self,
        initial_seeds: List[str],
        iterations: int = 100,
        early_stop_on_breach: bool = True,
    ) -> Dict:
        """
        Execute the MCTS-based fuzzing attack against AgentDojo.
        
        Args:
            initial_seeds: List of initial attack prompts
            iterations: Number of MCTS iterations
            early_stop_on_breach: Stop on first successful breach
            
        Returns:
            Dictionary with results and statistics
        """
        logger.info(f"Starting AgentVigil attack on AgentDojo with goal: {self.goal}")
        
        self.results = self.mcts.search(
            initial_seeds=initial_seeds,
            iterations=iterations,
            early_stop_on_breach=early_stop_on_breach,
        )
        
        return self.results
    
    def get_results(self) -> Optional[Dict]:
        """Get the latest search results."""
        return self.results
    
    def print_summary(self) -> None:
        """Print a human-readable summary of the attack."""
        if not self.results:
            print("No results available. Run the attack first.")
            return
        
        print("\n" + "="*70)
        print("AgentVigil-AgentDojo Attack Summary")
        print("="*70)
        print(f"Goal: {self.goal}")
        print(f"Iterations completed: {self.results['iterations']}")
        print(f"Total agent queries: {self.results['total_queries']}")
        print(f"Nodes explored: {self.results['total_nodes']}")
        print(f"Breaches found: {self.results['breaches_found']}")
        print(f"\nTree Statistics:")
        print(f"  Max depth: {self.results['tree_stats']['max_depth']}")
        print(f"  Avg visits per node: {self.results['tree_stats']['avg_visits']:.2f}")
        print(f"\nBest prompt discovered:")
        print(f"  Score: {self.results['best_score']:.3f}")
        print(f"  Prompt: {self.results['best_prompt']}")
        
        if self.results['successful_prompts']:
            print(f"\nSuccessful injection prompts:")
            for i, (prompt, score) in enumerate(self.results['successful_prompts'], 1):
                print(f"  {i}. [{score:.1f}] {prompt[:60]}...")
        
        print("="*70 + "\n")
    
    def get_tree_stats(self) -> Dict:
        """Get detailed statistics about the search tree."""
        return self.mcts.get_tree_stats()
    
    def get_attack_transcript(self) -> List[Dict]:
        """Get all query/response pairs from the attack."""
        return self.target.responses
