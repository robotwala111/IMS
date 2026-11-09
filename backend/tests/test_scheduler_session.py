import pytest

from app.services.scheduler import SchedulerService


class FakeSession:
    def __init__(self):
        self.rollback_calls = 0
        self.close_calls = 0

    async def rollback(self):
        self.rollback_calls += 1

    async def close(self):
        self.close_calls += 1


@pytest.mark.asyncio
async def test_scheduler_session_is_closed_after_success():
    scheduler = SchedulerService()
    session = FakeSession()
    scheduler._session_factory = lambda: session

    async with scheduler._db_session() as yielded:
        assert yielded is session

    assert session.rollback_calls == 0
    assert session.close_calls == 1


@pytest.mark.asyncio
async def test_scheduler_session_is_rolled_back_and_closed_after_failure():
    scheduler = SchedulerService()
    session = FakeSession()
    scheduler._session_factory = lambda: session

    with pytest.raises(RuntimeError, match="job failed"):
        async with scheduler._db_session():
            raise RuntimeError("job failed")

    assert session.rollback_calls == 1
    assert session.close_calls == 1

