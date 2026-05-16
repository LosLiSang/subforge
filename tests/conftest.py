import pytest


@pytest.fixture
def test_data_dir(tmp_path):
    """Temporary directory for test data files."""
    return tmp_path
