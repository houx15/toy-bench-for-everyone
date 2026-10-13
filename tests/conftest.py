import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEMO_KIT = REPO / "examples" / "demo-kit"


@pytest.fixture
def kit_dir(tmp_path: Path) -> Path:
    """A private copy of the demo kit, so tests can write calibration files into it."""
    dest = tmp_path / "kit"
    shutil.copytree(DEMO_KIT, dest)
    return dest
