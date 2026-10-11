"""KYA flow for AgentDojo: the payload is planted in the environment the agent reads."""
from kya.flows.base import KYAFlow, format_collected_information, format_tactics  # noqa: F401  (re-exported)


class AgentDojoFlow(KYAFlow):
    BANNER = "Starting Pentesting (Environment Injection - With Recon)..."

    def _inject(self, content):
        # Fills every injection slot reachable by the user task, then reruns the task from scratch.
        messages, security, utility = self.agents_dict['session'].inject_prompt_via_environment(content)
        if security:
            print("[+] Attack succeeded (security goal achieved programmatically). Skipping evaluator.")
        return str(messages), security, utility
