"""Bilgi tabani servis katmani. issues.csv, script manifestosu ve gecmis verileri toplar."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from db import list_tasks


@dataclass(slots=True)
class KnowledgeResult:
    source: str
    content: str
    confidence: float


class KnowledgeService:
    def __init__(self, base_dir: Path | None = None, db_path: Path | None = None):
        if base_dir is None:
            self.base_dir = Path(__file__).resolve().parent.parent
        else:
            self.base_dir = base_dir
            
        self.issues_path = self.base_dir / "knowledge" / "issues.csv"
        self.manifest_path = self.base_dir / "scripts" / "manifest.json"
        self.db_path = db_path

    @lru_cache(maxsize=1)
    def load_script_catalog(self) -> list[dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        with self.manifest_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)

        catalog: list[dict[str, Any]] = []
        for item in raw.get("scripts", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            aliases = [str(alias).strip() for alias in item.get("aliases", []) if str(alias).strip()]
            aliases.append(name.replace("_", " "))
            catalog.append(
                {
                    "name": name,
                    "aliases": tuple(dict.fromkeys(alias.lower() for alias in aliases if alias)),
                    "description": item.get("description", ""),
                }
            )
        return catalog

    def search_issues(self, normalized_text: str) -> KnowledgeResult | None:
        if not self.issues_path.exists():
            return None

        best_match = None
        best_score = 0

        try:
            with self.issues_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    problem = str(row.get("problem", "")).lower()
                    symptoms = str(row.get("symptoms", "")).lower()
                    
                    # Basit bir skorlama mantigi (en az 2 puan lazim)
                    score = 0
                    for word in problem.split() + symptoms.split():
                        if len(word) > 4 and word in normalized_text:
                            score += 1
                            
                    if score > best_score and score >= 2:
                        best_score = score
                        steps = row.get("solution_steps", "")
                        script = row.get("bat_script", "")
                        rate = row.get("success_rate", "?")
                        content = f"Onerilen cozum: {steps} (Script: {script}, Basari: {rate})"
                        best_match = KnowledgeResult(source="issues.csv", content=content, confidence=min(0.5 + (score * 0.1), 0.95))
        except Exception:
            pass

        return best_match
        
    def search_recent_tasks(self, normalized_text: str) -> KnowledgeResult | None:
        if not self.db_path:
            return None
            
        recent_tasks = list_tasks(self.db_path, limit=20)
        # Sadece son kullanici komutlarini ara (su anki parser icin fazla karmasik yapmamiza gerek yok ancak altyapiyi atalim)
        return None

    def get_knowledge_hint(self, normalized_text: str) -> str | None:
        issues_result = self.search_issues(normalized_text)
        if issues_result:
            return f"[{issues_result.source}] {issues_result.content}"
        return None

    def get_script_catalog_summary(self, limit: int = 20) -> str:
        items = self.load_script_catalog()[:limit]
        if not items:
            return "Yok"
        summary_rows: list[str] = []
        for item in items:
            aliases = ", ".join(item["aliases"][:4]) if item.get("aliases") else "-"
            description = str(item.get("description", "")).strip() or "-"
            summary_rows.append(f"- {item['name']}: {description} | aliases: {aliases}")
        return "\n".join(summary_rows)
