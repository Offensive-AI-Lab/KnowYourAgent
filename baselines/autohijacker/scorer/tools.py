"""Tools for the Scorer agent."""

from crewai.tools import BaseTool
from pydantic import Field, BaseModel
from typing import Type


class ParseScoreInput(BaseModel):
    """Input schema for ParseScoreTool."""
    raw_output: str = Field(
        ...,
        description="The raw text output from the Scorer agent containing the score."
    )


class ParseScoreTool(BaseTool):
    """Tool for parsing the Scorer agent's output to extract a strict numerical score."""

    name: str = "parse_score"
    description: str = ""
    args_schema: Type[BaseModel] = ParseScoreInput

    def _run(self, raw_output: str) -> float:
        """Parse the raw output string and extract a numerical score.

        Attempts to find and return a float/integer score from the text.
        Returns 0.0 if no valid score is found.
        """
        import re

        # Try to find a number in the output (integer or float)
        match = re.search(r"(\d+\.?\d*)", raw_output.strip())
        if match:
            return float(match.group(1))

        return 0.0
