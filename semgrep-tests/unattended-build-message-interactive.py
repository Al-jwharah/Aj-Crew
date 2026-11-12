# Fixtures for semgrep/unattended-build-message-interactive.yaml, exercised by
# `semgrep --test` in the SAST job. `ruleid:` asserts the NEXT line MUST
# match; `ok:` asserts it must NOT. The negatives pin that an explicit
# interactive=False clears both call shapes wherever it sits in the call.


async def _defaulted(ctx, run_in_embed_pool, _io, text, key):
    # ruleid: ajcrew.unattended-build-message-interactive
    await run_in_embed_pool(ctx.build_message, text, True, key, agent=None)
    # ruleid: ajcrew.unattended-build-message-interactive
    await _io(ctx.context_builder.build_message, text, True, session_key=key)
    # ruleid: ajcrew.unattended-build-message-interactive
    ctx.build_message(text, True, key)
    # ruleid: ajcrew.unattended-build-message-interactive
    await run_in_embed_pool(ctx.build_message, text, True, key, interactive=True)


async def _non_interactive(ctx, run_in_embed_pool, _io, text, key):
    # ok: ajcrew.unattended-build-message-interactive
    await run_in_embed_pool(ctx.build_message, text, True, key, interactive=False)
    # ok: ajcrew.unattended-build-message-interactive
    await run_in_embed_pool(ctx.build_message, text, True, interactive=False, agent=None)
    # ok: ajcrew.unattended-build-message-interactive
    await _io(ctx.context_builder.build_message, text, True, interactive=False)
    # ok: ajcrew.unattended-build-message-interactive
    ctx.build_message(text, True, key, interactive=False)
