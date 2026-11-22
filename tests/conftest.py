import pytest

from app.config import get_params
from app.scenario import build_day_bank


@pytest.fixture(scope="session")
def P():
    return get_params("default")


@pytest.fixture(scope="session")
def bank(P):
    return build_day_bank(P)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app import main

    with TestClient(main.app) as c:
        yield c
