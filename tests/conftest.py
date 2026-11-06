from pathlib import Path

import pytest

from back.parser import Upload


@pytest.fixture
def uploads() -> list[Upload]:
    return [
        Upload(path.name, path.read_text(encoding="utf-8"))
        for path in sorted((Path(__file__).parent.parent / "data").glob("*.txt"))
    ]
