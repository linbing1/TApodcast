import json
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


def atomic_write_text(path: str | Path, content: str) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def atomic_write_json(path: str | Path, value: BaseModel | Any) -> Path:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON artifact: {source}") from error


def read_model(path: str | Path, model: type[ModelT]) -> ModelT:
    return model.model_validate(read_json(path))
