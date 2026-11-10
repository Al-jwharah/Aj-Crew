# Fixtures for semgrep/slot-live-view-await.yaml, exercised by `semgrep --test`
# in the SAST job. `ruleid:` asserts the NEXT line MUST match; `ok:` asserts it
# must NOT.


async def _a_loop_over_a_live_view_that_awaits(state, self, save, lock, rows):
    for slot in state._slots.values():
        # ruleid: ajcrew.slot-live-view-await
        await save(slot)
    for key, slot in self._slots.items():
        if slot:
            # ruleid: ajcrew.slot-live-view-await
            await save(key)
    for key in state._slots.keys():
        # ruleid: ajcrew.slot-live-view-await
        async with lock:
            pass
    for key in state._slots:
        # ruleid: ajcrew.slot-live-view-await
        async for row in rows():
            pass
    for slot in getattr(state, "_slots", {}).values():
        # ruleid: ajcrew.slot-live-view-await
        await save(slot)


async def _a_snapshot_or_no_await_is_fine(state, save):
    for slot in list(state._slots.values()):
        # ok: ajcrew.slot-live-view-await
        await save(slot)
    for slot in state._slots.copy():
        # ok: ajcrew.slot-live-view-await
        await save(slot)
    for slot in state._slots.values():
        # ok: ajcrew.slot-live-view-await
        save(slot)
    for folder in state._folders.values():
        # ok: ajcrew.slot-live-view-await
        await save(folder)
