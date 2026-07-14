from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


SCHEMA_VERSION = "1.0"
WORKER_CALCULATION_BASIS = (
    "recommended_workers=min(memory_worker_limit,cpu_worker_limit,business_concurrency_limit); "
    "memory_worker_limit=max(1,floor(memory_budget_bytes/observed_peak_process_tree_rss_bytes)); "
    "cpu_worker_limit=max(1,floor(logical_cpu_count/2))"
)
VALIDATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0


def validate_validation_id(value: Any) -> str:
    if not isinstance(value, str) or not VALIDATION_ID_PATTERN.fullmatch(value):
        raise ValueError("validation_id must be 6-128 safe ASCII characters")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def execution_identity(plugin_root: Path, plugin_name: str) -> Dict[str, Dict[str, str]]:
    return {
        "plugin": {"name": plugin_name, "root": str(Path(plugin_root).resolve())},
        "interpreter": {"executable": sys.executable, "version": sys.version.split()[0]},
    }


def envelope(
    validation_id: str, campaign_id: str, recorded_at_utc: str
) -> Dict[str, str]:
    return {
        "schema_version": SCHEMA_VERSION,
        "validation_id": validation_id,
        "campaign_id": campaign_id,
        "recorded_at_utc": recorded_at_utc,
    }


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
