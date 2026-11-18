import shutil
from pathlib import Path

import pytest

from fbposter.config import load_config

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A throwaway copy of the project config with an empty queue and history."""
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    shutil.copytree(REPO / "niches", tmp_path / "niches")
    shutil.copytree(REPO / "assets", tmp_path / "assets")
    (tmp_path / "content" / "queue").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def cfg(root: Path):
    return load_config(root)
