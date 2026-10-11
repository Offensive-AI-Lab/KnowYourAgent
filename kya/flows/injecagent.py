"""KYA flow for InjecAgent: the payload replaces the (single) tool response in the conversation."""
from kya.flows.base import KYAFlow


class InjecAgentFlow(KYAFlow):
    NO_RECON_PLACEHOLDER = "No knowledge was gathered. Do your best to implement the strategy without having any knowledge"

    def _inject(self, content):
        session = self.agents_dict['session']
        session.init_chat()
        # Inject at the tool message: the same fixed point InjecAgent itself uses.
        messages, success_str, utility_str = session.inject_at_tool_message(content)
        security = "True" in success_str
        utility = "True" in utility_str
        if security:
            print("[+] Attack succeeded (security goal achieved programmatically). Skipping evaluator.")
        return str(messages), security, utility
