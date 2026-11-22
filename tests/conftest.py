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
def client(bank):
    from unittest import mock

    from fastapi.testclient import TestClient

    from app import main

    # reuse the session bank instead of rebuilding it in the lifespan; the real
    # cold build is covered by test_api::test_cold_start_under_60s
    with (
        mock.patch.object(main, "build_day_bank", return_value=bank),
        TestClient(main.app) as c,
    ):
        yield c
