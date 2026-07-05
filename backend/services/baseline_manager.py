from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

from services.regression_framework import BaselineResult


class BaselineManager:
    def __init__(self, base_directory: str | None = None):
        root = base_directory or os.path.join(os.getcwd(), "benchmark_baselines")
        self.base_directory = Path(root)
        self.base_directory.mkdir(parents=True, exist_ok=True)

    def save_baseline(self, baseline: BaselineResult) -> str:
        file_path = self._path_for_version(baseline.version)
        payload = baseline.to_dict()
        file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(file_path)

    def load_baseline(self, version: str) -> BaselineResult:
        file_path = self._path_for_version(version)
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return BaselineResult.from_dict(payload)

    def delete_baseline(self, version: str) -> bool:
        file_path = self._path_for_version(version)
        if not file_path.exists():
            return False
        file_path.unlink()
        return True

    def list_baselines(self) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        for file_path in sorted(self.base_directory.glob("*.json")):
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
                baseline = BaselineResult.from_dict(payload)
                items.append(
                    {
                        "id": baseline.id,
                        "version": baseline.version,
                        "created_at": baseline.created_at,
                        "file_path": str(file_path),
                    }
                )
            except Exception:
                items.append(
                    {
                        "id": "",
                        "version": file_path.stem,
                        "created_at": "",
                        "file_path": str(file_path),
                    }
                )
        return items

    def _path_for_version(self, version: str) -> Path:
        normalized = self._normalize_version(version)
        return self.base_directory / f"{normalized}.json"

    def _normalize_version(self, version: str) -> str:
        value = str(version or "").strip() or "default"
        allowed = []
        for char in value:
            if char.isalnum() or char in {"-", "_", "."}:
                allowed.append(char)
            else:
                allowed.append("_")
        return "".join(allowed)
