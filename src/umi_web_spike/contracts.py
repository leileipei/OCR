from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class OcrBlock:
    text: str
    score: float
    box: Tuple[Tuple[float, float], ...]

    @classmethod
    def from_plugin_dict(cls, value: Dict[str, Any]) -> "OcrBlock":
        box = value.get("box")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("block.box must contain four points")
        points = tuple((float(point[0]), float(point[1])) for point in box)
        return cls(text=str(value["text"]), score=float(value["score"]), box=points)


@dataclass(frozen=True)
class OcrResult:
    code: int
    blocks: Tuple[OcrBlock, ...] = ()
    error: Optional[str] = None

    @classmethod
    def from_plugin_dict(cls, value: Dict[str, Any]) -> "OcrResult":
        code = int(value["code"])
        data = value.get("data")
        if code == 100:
            if not isinstance(data, list):
                raise ValueError("data must be a list for code 100")
            return cls(code=code, blocks=tuple(OcrBlock.from_plugin_dict(item) for item in data))
        return cls(code=code, error=str(data))


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    name: str
    details: Dict[str, Any]

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
