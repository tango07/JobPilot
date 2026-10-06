import asyncio

import pytest
from fastapi import HTTPException

from backend.app import exclusive_browser_run


def test_browser_operations_do_not_overlap():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        @exclusive_browser_run("test operation")
        async def run():
            started.set()
            await release.wait()
            return "done"

        first = asyncio.create_task(run())
        await started.wait()
        with pytest.raises(HTTPException) as error:
            await run()
        assert error.value.status_code == 409
        release.set()
        assert await first == "done"

    asyncio.run(scenario())
