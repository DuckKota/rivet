"""Repository layout contract: payload lives under content/, CLI code under src/."""
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import manifest  # noqa: E402  pylint: disable=wrong-import-position

PAYLOAD_DIRS = ("commands", "skills", "instructions", "plugins", "themes")


def test_manifest_local_sources_live_under_content():
    data = manifest.load(REPO / "manifest.toml")
    for artifact in data["artifacts"]:
        sources = []
        if "src" in artifact:
            sources.append(artifact["src"])
        for entry in artifact.get("entries") or []:
            if "src" in entry:
                sources.append(entry["src"])
        for source in sources:
            assert source.startswith("content/"), (
                f"{artifact['name']}: local source {source!r} is outside content/"
            )


def test_payload_directories_live_under_content():
    for name in PAYLOAD_DIRS:
        assert (REPO / "content" / name).is_dir(), f"content/{name} is missing"
        assert not (REPO / "src" / name).exists(), f"src/{name} should not exist"
