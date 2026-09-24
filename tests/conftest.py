from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def test_data_dir(tmp_path):
    """Temporary directory for test data files."""
    return tmp_path


def pytest_collection_modifyitems(items):
    """Automatically mark tests based on their directory location."""
    for item in items:
        path_str = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path_str:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path_str:
            item.add_marker(pytest.mark.integration)
