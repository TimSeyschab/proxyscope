import os
import shlex
import shutil
import subprocess
from pathlib import Path


def resolve_editor_command() -> str | None:
    editor = os.environ.get("EDITOR")
    if editor:
        parts = shlex.split(editor)
        if parts and shutil.which(parts[0]) is not None:
            return editor
    return next((name for name in ("nano", "vim", "vi") if shutil.which(name) is not None), None)


def run_editor(editor: str, file_path: Path) -> None:
    subprocess.run([*shlex.split(editor), str(file_path)], check=True)
