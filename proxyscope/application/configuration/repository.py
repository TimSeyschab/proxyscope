import json
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from proxyscope.application.configuration.models import ConfigDocument, RuntimeSettings
from proxyscope.application.configuration.serialization import parse_config_payload, serialize_config_document


@runtime_checkable
class ConfigRepository(Protocol):
    def load(self, path: Path) -> ConfigDocument: ...

    def save(self, path: Path, document: ConfigDocument) -> None: ...


class JsonConfigRepository:
    def load(self, path: Path) -> ConfigDocument:
        if not path.exists():
            return ConfigDocument(settings=RuntimeSettings())
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in config {path}: {exc.msg} at line {exc.lineno}, column {exc.colno}."
            ) from exc
        return parse_config_payload(payload)

    def save(self, path: Path, document: ConfigDocument) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = serialize_config_document(document)
        serialized = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(serialized)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise
