from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

# pipeline/src/pitwall/config.py → repository root
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path
    bundle_dir: Path
    openf1_url: str


def load_config(path: Path = CONFIG_DIR / "pipeline.yaml") -> PipelineConfig:
    raw = yaml.safe_load(path.read_text())
    config = PipelineConfig.model_validate(raw)
    return config.model_copy(
        update={
            "data_dir": REPO_ROOT / config.data_dir,
            "bundle_dir": REPO_ROOT / config.bundle_dir,
        }
    )
