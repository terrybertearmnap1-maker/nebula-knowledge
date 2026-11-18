from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        web_search_provider="disabled",
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
