import asyncio

import ui.repl_termux as repl


def test_spinner_does_not_tick_while_awaiting_input(monkeypatch):
    real_sleep = asyncio.sleep

    async def fake_sleep(_delay):
        raise AssertionError("spinner ticked while input was awaited")

    async def run():
        active = asyncio.Event()
        monkeypatch.setattr(repl.asyncio, "sleep", fake_sleep)
        task = asyncio.create_task(repl._toolbar_spinner_loop(active))
        await real_sleep(0)
        active.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


def test_spinner_resumes_after_input(monkeypatch):
    ticks = 0
    real_sleep = asyncio.sleep

    async def fake_sleep(_delay):
        nonlocal ticks
        ticks += 1
        raise asyncio.CancelledError

    async def run():
        active = asyncio.Event()
        monkeypatch.setattr(repl.asyncio, "sleep", fake_sleep)
        task = asyncio.create_task(repl._toolbar_spinner_loop(active))
        await real_sleep(0)
        assert ticks == 0
        active.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert ticks == 1

    asyncio.run(run())
