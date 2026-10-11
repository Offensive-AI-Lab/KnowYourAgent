"""Tools for the Prompter agent."""

from crewai.tools import BaseTool
from pydantic import Field
from typing import Any, List, Dict, Type
from pydantic import BaseModel


class ReadAttackMemoryInput(BaseModel):
    """Input schema for ReadAttackMemoryTool."""
    attack_memory: str = Field(
        ...,
        description="JSON string of the attack memory containing past attack logs."
    )


class ReadAttackMemoryTool(BaseTool):
    """Tool for reading and parsing the attack memory (A) containing logs of past
    successful and failed attacks."""

    name: str = "read_attack_memory"
    description: str = ""
    args_schema: Type[BaseModel] = ReadAttackMemoryInput

    def _run(self, attack_memory: str) -> str:
        """Parse and format the attack memory for the Prompter agent."""
        import json

        try:
            memory_list = json.loads(attack_memory)
        except (json.JSONDecodeError, TypeError):
            return "No valid attack memory available."

        if not memory_list:
            return "Attack memory is empty. No prior attack logs to reference."

        formatted_entries = []
        for i, entry in enumerate(memory_list):
            formatted_entry = (
                f"--- Attack Log {i + 1} ---\n"
                f"Original Data (D): {entry.get('D', 'N/A')}\n"
                f"Attack Goal (G): {entry.get('G', 'N/A')}\n"
                f"Meta-Prompt (M): {entry.get('M', 'N/A')}\n"
                f"Injection Data (D_hat): {entry.get('D_hat', 'N/A')}\n"
                f"Score (S): {entry.get('S', 'N/A')}\n"
            )
            formatted_entries.append(formatted_entry)

        return "\n".join(formatted_entries)


class FormatMetaPromptInput(BaseModel):
    """Input schema for FormatMetaPromptTool."""
    raw_meta_prompt: str = Field(
        ...,
        description="The raw meta-prompt text to format."
    )


class FormatMetaPromptTool(BaseTool):
    """Tool for formatting the generated meta-prompt into a structured output."""

    name: str = "format_meta_prompt"
    description: str = ""
    args_schema: Type[BaseModel] = FormatMetaPromptInput

    def _run(self, raw_meta_prompt: str) -> str:
        """Format the meta-prompt into a clean, structured output."""
        formatted = (
            "=== META-PROMPT ===\n"
            f"{raw_meta_prompt.strip()}\n"
            "=== END META-PROMPT ==="
        )
        return formatted
