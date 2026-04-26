from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from app.core.config import CONFIG_DIR


@dataclass(frozen=True)
class AdjustmentCategory:
    key: str
    label: str
    adjustment_type: str | None
    match_contains: tuple[str, ...]
    adcode: str


class CategoryRegistry:
    def __init__(self, categories: list[AdjustmentCategory]) -> None:
        self._categories = categories

    @property
    def categories(self) -> list[AdjustmentCategory]:
        return list(self._categories)

    def by_key(self, key: str) -> AdjustmentCategory | None:
        normalized = key.strip().lower()
        return next((item for item in self._categories if item.key == normalized), None)

    def detect(self, adjustment_name: str, adjustment_type: str = "") -> str | None:
        name = " ".join(adjustment_name.upper().split())
        adj_type = adjustment_type.upper().strip()
        for category in self._categories:
            type_matches = not category.adjustment_type or category.adjustment_type.upper() == adj_type
            name_matches = any(token.upper() in name for token in category.match_contains)
            if type_matches and name_matches:
                return category.key
        for category in self._categories:
            if any(token.upper() in name for token in category.match_contains):
                return category.key
        return None


def load_category_registry(path: Path | None = None) -> CategoryRegistry:
    config_path = path or CONFIG_DIR / "adjustment-categories.json"
    raw_items = json.loads(config_path.read_text(encoding="utf-8"))
    categories = [
        AdjustmentCategory(
            key=str(item["key"]).strip().lower(),
            label=str(item["label"]),
            adjustment_type=str(item.get("adjustment_type") or "") or None,
            match_contains=tuple(str(token).upper() for token in item.get("match_contains", [])),
            adcode=str(item.get("adcode", "")),
        )
        for item in raw_items
    ]
    return CategoryRegistry(categories)
