import argparse
import os
import subprocess
from pathlib import Path

from loguru import logger

from pitwall.config import REPO_ROOT, load_config
from pitwall.export.bundle import export_bundle
from pitwall.export.contract import write_schemas
from pitwall.ingest.fastf1_race import fetch_race
from pitwall.ingest.storage import write_race


def _git_sha() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:12]
    result = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(prog="pitwall")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="pull one race into the canonical tables")
    ingest.add_argument("--season", type=int, required=True)
    ingest.add_argument("--round", type=int, required=True)

    commands.add_parser("export", help="write the static bundle from all ingested races")

    contract = commands.add_parser("contract", help="write JSON Schema for the export contract")
    contract.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    config = load_config()

    match args.command:
        case "ingest":
            tables = fetch_race(args.season, args.round, config.data_dir / "fastf1-cache")
            logger.info("wrote {}", write_race(config.data_dir, tables))
        case "export":
            export_bundle(config.data_dir, config.bundle_dir, _git_sha())
        case "contract":
            for path in write_schemas(args.out):
                logger.info("wrote {}", path)
