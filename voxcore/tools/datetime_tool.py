"""
GetCurrentDatetime tool.

Returns the current local date and time as a readable string.
No external dependencies. No parameters required.

Example LLM trigger: "What time is it?" / "What's today's date?"
"""
from datetime import datetime

from voxcore.tools.base import BaseTool


class GetCurrentDatetime(BaseTool):
    name = "get_current_datetime"
    description = (
        "Returns the current local date and time. "
        "Use this when the user asks about the time, date, day of the week, or anything time-related."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, **kwargs) -> str:
        now = datetime.now()
        return now.strftime("%A, %B %d, %Y at %I:%M %p")
