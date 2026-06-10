import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from proxyscope.policies.models import PolicyRule
from proxyscope.policies.serialization import parse_policy_rule, serialize_policy_rule


def edit_policy_rule_with_external_editor(rule: PolicyRule) -> tuple[bool, PolicyRule | None, str]:
    editor = _resolve_editor_command()
    if editor is None:
        return False, None, "No editor found. Set $EDITOR (or install nano/vim/vi)."

    payload = serialize_policy_rule(rule)
    try:
        with tempfile.TemporaryDirectory(prefix="tproxy-policy-") as tmp_dir:
            file_path = Path(tmp_dir) / "policy.json"
            file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

            print(f"[tproxy] Editing policy in {file_path.name} ({editor})")
            _run_editor(editor, file_path)

            edited_payload = json.loads(file_path.read_text(encoding="utf-8"))
            parsed = parse_policy_rule(edited_payload)
            if parsed is None:
                return False, None, "Edited policy is invalid JSON schema."
            if parsed.name != rule.name:
                parsed = PolicyRule(
                    name=rule.name,
                    enabled=parsed.enabled,
                    priority=parsed.priority,
                    action=parsed.action,
                    match=parsed.match,
                )
            return True, parsed, f"Policy updated: {rule.name}"
    except Exception as exc:  # noqa: BLE001
        return False, None, f"Policy edit failed ({exc})."


def _resolve_editor_command() -> str | None:
    env_editor = os.environ.get("EDITOR")
    if env_editor:
        parts = shlex.split(env_editor)
        if parts and shutil.which(parts[0]) is not None:
            return env_editor

    for candidate in ("nano", "vim", "vi"):
        if shutil.which(candidate) is not None:
            return candidate
    return None


def _run_editor(editor: str, file_path: Path) -> None:
    cmd = shlex.split(editor) + [str(file_path)]
    subprocess.run(cmd, check=True)
