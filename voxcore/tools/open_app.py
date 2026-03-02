"""
OpenApplication tool.

Launches a local application by name using the OS shell.
Includes common Windows application aliases so the LLM can use
natural names ("calculator", "spotify") instead of executable names.

Example LLM trigger: "Open Spotify" / "Launch calculator"
"""
import subprocess
import logging

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Maps common spoken names to Windows executable names.
# Add entries here to support additional applications.
_APP_ALIASES: dict[str, str] = {
    "calculator":     "calc",
    "notepad":        "notepad",
    "paint":          "mspaint",
    "file explorer":  "explorer",
    "explorer":       "explorer",
    "task manager":   "taskmgr",
    "chrome":         "chrome",
    "firefox":        "firefox",
    "edge":           "msedge",
    "spotify":        "spotify",
    "discord":        "discord",
    "word":           "winword",
    "excel":          "excel",
    "powerpoint":     "powerpnt",
    "vlc":            "vlc",
    "vscode":         "code",
    "visual studio code": "code",
    "terminal":       "wt",
    "cmd":            "cmd",
    "powershell":     "powershell",
}


class OpenApplication(BaseTool):
    name = "open_application"
    description = (
        "Opens an application on the local machine by name. "
        "Supports common apps like 'calculator', 'notepad', 'chrome', 'spotify', "
        "'discord', 'vscode', 'terminal', and others. "
        "Use the most natural name for the application."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the application to open, e.g. 'calculator', 'spotify'.",
            }
        },
        "required": ["name"],
    }

    def execute(self, name: str, **kwargs) -> str:
        normalized = name.strip().lower()
        executable = _APP_ALIASES.get(normalized, normalized)
        try:
            # shell=True + 'start' delegates to Windows app resolver;
            # works for both .exe names and registered app names.
            subprocess.Popen(f'start "" "{executable}"', shell=True)
            logger.info(f"Launched application: '{executable}' (requested: '{name}')")
            return f"Opened {name}."
        except Exception as e:
            logger.error(f"Failed to open '{name}' (executable: '{executable}'): {e}")
            return f"Failed to open '{name}': {e}"
