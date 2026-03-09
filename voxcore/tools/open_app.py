"""
OpenApplication tool.

Launches a local application by name using the OS shell.
Includes per-platform application aliases so the LLM can use
natural names ("calculator", "spotify") instead of executable names.

Supported platforms: Windows, macOS, Linux.

Example LLM trigger: "Open Spotify" / "Launch calculator"
"""
import sys
import subprocess
import logging

from voxcore.tools.base import BaseTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-platform aliases: maps spoken names to executable / app names.
# Cross-platform apps (chrome, firefox, spotify, etc.) that use the same
# command on all platforms are defined once in _COMMON_ALIASES.
# ---------------------------------------------------------------------------

_COMMON_ALIASES: dict[str, str] = {
    "chrome":              "chrome" if sys.platform == "win32" else "google-chrome" if sys.platform == "linux" else "Google Chrome",
    "firefox":             "firefox" if sys.platform != "darwin" else "Firefox",
    "spotify":             "spotify" if sys.platform != "darwin" else "Spotify",
    "discord":             "discord" if sys.platform != "darwin" else "Discord",
    "vlc":                 "vlc" if sys.platform != "darwin" else "VLC",
    "vscode":              "code",
    "visual studio code":  "code",
}

_WINDOWS_ALIASES: dict[str, str] = {
    "calculator":     "calc",
    "notepad":        "notepad",
    "paint":          "mspaint",
    "file explorer":  "explorer",
    "explorer":       "explorer",
    "task manager":   "taskmgr",
    "edge":           "msedge",
    "word":           "winword",
    "excel":          "excel",
    "powerpoint":     "powerpnt",
    "terminal":       "wt",
    "cmd":            "cmd",
    "powershell":     "powershell",
}

_MACOS_ALIASES: dict[str, str] = {
    "calculator":     "Calculator",
    "notes":          "Notes",
    "text edit":      "TextEdit",
    "textedit":       "TextEdit",
    "file explorer":  "Finder",
    "finder":         "Finder",
    "safari":         "Safari",
    "terminal":       "Terminal",
    "activity monitor": "Activity Monitor",
    "system settings": "System Settings",
    "preview":        "Preview",
    "music":          "Music",
    "pages":          "Pages",
    "numbers":        "Numbers",
    "keynote":        "Keynote",
}

_LINUX_ALIASES: dict[str, str] = {
    "calculator":     "gnome-calculator",
    "notepad":        "gedit",
    "text editor":    "gedit",
    "file explorer":  "nautilus",
    "files":          "nautilus",
    "terminal":       "gnome-terminal",
    "system monitor":  "gnome-system-monitor",
    "settings":       "gnome-control-center",
}

# Select the right alias table for the current platform
if sys.platform == "win32":
    _APP_ALIASES = {**_COMMON_ALIASES, **_WINDOWS_ALIASES}
elif sys.platform == "darwin":
    _APP_ALIASES = {**_COMMON_ALIASES, **_MACOS_ALIASES}
else:
    _APP_ALIASES = {**_COMMON_ALIASES, **_LINUX_ALIASES}


# ---------------------------------------------------------------------------
# Per-platform launch function
# ---------------------------------------------------------------------------

def _launch(executable: str) -> None:
    """Launch an application using the platform-appropriate method."""
    if sys.platform == "win32":
        subprocess.Popen(f'start "" "{executable}"', shell=True)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", executable])
    else:
        subprocess.Popen([executable])


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
            _launch(executable)
            logger.info(f"Launched application: '{executable}' (requested: '{name}')")
            return f"Opened {name}."
        except Exception as e:
            logger.error(f"Failed to open '{name}' (executable: '{executable}'): {e}")
            return f"Failed to open '{name}': {e}"
