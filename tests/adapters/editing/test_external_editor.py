from pathlib import Path
from unittest.mock import patch

from proxyscope.adapters.editing.external_editor import resolve_editor_command, run_editor


def test_editor_environment_preserves_arguments():
    with patch.dict("os.environ", {"EDITOR": '"/custom/my editor" --wait'}, clear=True):
        with patch("proxyscope.adapters.editing.external_editor.shutil.which", return_value="/custom/my editor") as which:
            assert resolve_editor_command() == '"/custom/my editor" --wait'
            which.assert_called_once_with("/custom/my editor")


def test_editor_falls_back_to_available_command():
    with patch.dict("os.environ", {}, clear=True):
        with patch("proxyscope.adapters.editing.external_editor.shutil.which", side_effect=[None, "/bin/vim"]):
            assert resolve_editor_command() == "vim"


def test_editor_unavailable():
    with patch.dict("os.environ", {}, clear=True):
        with patch("proxyscope.adapters.editing.external_editor.shutil.which", return_value=None):
            assert resolve_editor_command() is None


def test_editor_runs_quoted_arguments_without_shell():
    with patch("proxyscope.adapters.editing.external_editor.subprocess.run") as run:
        run_editor('"/custom/my editor" --wait', Path("request body.txt"))
        run.assert_called_once_with(["/custom/my editor", "--wait", "request body.txt"], check=True)
