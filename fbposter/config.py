"""Load config.yaml plus the active niche file into typed objects."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent


class Pillar(BaseModel):
    """One recurring content type (e.g. "ready-made prompt", "myth vs fact")."""

    id: str
    name: str
    description: str
    weight: float = 1.0
    image: bool = True


class Niche(BaseModel):
    id: str
    title: str
    audience: str
    voice: str
    language: str = "Egyptian Arabic (عامية مصرية)"
    pillars: list[Pillar]
    hashtags: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    image_ratio: float | None = None

    @field_validator("pillars")
    @classmethod
    def _non_empty(cls, v: list[Pillar]) -> list[Pillar]:
        if not v:
            raise ValueError("niche must define at least one pillar")
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("pillar ids must be unique")
        return v


class PageCfg(BaseModel):
    name: str
    handle: str = ""
    tagline: str = ""
    cover_points: list[str] = Field(default_factory=list)


class ClaudeCfg(BaseModel):
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    batch_size: int = 7


class PostingCfg(BaseModel):
    queue_target: int = 14
    require_approval: bool = False
    auto_generate_when_queue_empty: bool = True
    image_ratio: float = 0.7


class FacebookCfg(BaseModel):
    graph_api_version: str = "v26.0"


class BrandCfg(BaseModel):
    background: str = "#0B1220"
    background_2: str = "#1E293B"
    accent: str = "#F59E0B"
    text: str = "#F8FAFC"
    muted: str = "#94A3B8"


class Config(BaseModel):
    page: PageCfg
    niche: Niche
    claude: ClaudeCfg = ClaudeCfg()
    posting: PostingCfg = PostingCfg()
    facebook: FacebookCfg = FacebookCfg()
    brand: BrandCfg = BrandCfg()
    root: Path = ROOT

    @property
    def queue_dir(self) -> Path:
        return self.root / "content" / "queue"

    @property
    def history_file(self) -> Path:
        return self.root / "content" / "history.jsonl"

    @property
    def fonts_dir(self) -> Path:
        return self.root / "assets" / "fonts"

    @property
    def image_ratio(self) -> float:
        if self.niche.image_ratio is not None:
            return self.niche.image_ratio
        return self.posting.image_ratio


def load_config(root: Path | None = None) -> Config:
    root = Path(root) if root else ROOT
    raw = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    niche_id = os.environ.get("FB_NICHE") or raw.get("niche")
    if not niche_id:
        raise ValueError("config.yaml must set `niche`")
    niche_path = root / "niches" / f"{niche_id}.yaml"
    if not niche_path.exists():
        available = ", ".join(sorted(p.stem for p in (root / "niches").glob("*.yaml")))
        raise FileNotFoundError(f"niche '{niche_id}' not found. Available: {available}")
    niche_raw = yaml.safe_load(niche_path.read_text(encoding="utf-8"))
    niche_raw["id"] = niche_id
    raw["niche"] = niche_raw
    raw["root"] = root
    return Config.model_validate(raw)
