"""A cron Bot Chat delivery survives a local RESET of the target conversation.

The producer pins the id it read from the target's store (``tools.bot_live_delivery``'s
``_bot_chat_tip``: the compression tip of the row titled ``Bot Chat``). A RESET is not a
compression step, so after a reset the pin keeps naming the LOGICAL id while the live route
entry points at the physical RESET SEGMENT. The pinned id and the entry's session id then differ
even though both name one conversation, and the door refused every delivery
``admission_conflict`` — forever, because the reset never rolls back and the pin never moves.

The admission identity is the authority on "one conversation": ``admission_owner`` answers the
creation id a physical row answers to (the compression root, then the local reset fork). The
door therefore admits a pinned id that IS the live entry's admission owner, and still refuses a
pin that names a DIFFERENT conversation.
"""
import pytest

from hermes_state_runtime import RuntimeStoreError

from tests.gateway import test_peer_dm_bot_chat_headless as _headless_gateway
from tests.waiting import async_wait_until

# The headless gateway fixture: one real authority over a SessionDB in a temp HERMES_HOME.
headless = _headless_gateway.headless
_local_owner = _headless_gateway._local_owner


async def _deliver(authority, key, *, pinned=None):
    """The cron producer's door: ``bot_relay.deliver`` on a local interactive connection, no
    author, pinned to the Bot Chat it discovered first."""
    from gateway.session_authorities import served_profile_name
    from gateway.session_bot import deliver
    from tools.bot_live_delivery import _bot_chat_tip
    home = authority.db.db_path.parent.resolve()
    if pinned is None:
        pinned = _bot_chat_tip(home)
    return await deliver(_local_owner(authority), dict(id=key * 32, profile=served_profile_name(home),
                                                       message='cron beat',
                                                       **({'session_id': pinned} if pinned else {})))


def _receipt(authority, key):
    """The delivery's receipt, once its turn ran to a terminal state."""
    from tools.bot_live_delivery import read_delivery_result
    home = authority.db.db_path.parent.resolve()
    return read_delivery_result(home, key * 32) or {}


async def _await_settled(authority, key):
    await async_wait_until(lambda: _receipt(authority, key).get('status') == 'settled',
                           timeout=10, interval=.05)


async def _reset_bot_chat(authority):
    """Reset the Bot Chat the way ``/new`` does (the production reset path), once the running
    turn has settled — a reset refuses a busy conversation (``session_busy``)."""
    store = authority.runner.session_store
    holder = authority.db.get_session_by_title('Bot Chat')
    entry = store.reset_session(holder['session_key'])
    return holder['id'], entry.session_id


@pytest.mark.asyncio
async def test_a_delivery_pinned_to_the_logical_id_lands_after_a_reset(headless):
    """The pinned id and the live segment name one conversation: the beat is admitted."""
    authority = headless.authority
    first = await _deliver(authority, 'a')
    assert first is not None and first.get('status') != 'failed', first
    await _await_settled(authority, 'a')

    logical, segment = await _reset_bot_chat(authority)
    assert segment != logical, 'the reset did not fork a new physical segment'

    # The producer's pin: the logical id (the title's tip — a reset is not a compression step).
    from tools.bot_live_delivery import _bot_chat_tip
    home = authority.db.db_path.parent.resolve()
    assert _bot_chat_tip(home) == logical, 'the reset segment is not a compression child'

    # The beat the producer pinned before the reset still lands: no admission_conflict.
    second = await _deliver(authority, 'b', pinned=logical)
    await _await_settled(authority, 'b')
    # It lands in the conversation the pin named — the reset did not fork a new conversation.
    assert second is not None and second.get('session_id') == logical, second
    assert _receipt(authority, 'b').get('session_id') == logical
    await async_wait_until(lambda: len(headless.executed) == 2, timeout=10, interval=.05)
    assert [sid for sid, _, _ in headless.executed] == [logical, logical]


@pytest.mark.asyncio
async def test_a_pin_naming_a_different_conversation_is_still_refused(headless):
    """The lineage is the ONLY thing that widens the pin: a foreign id is still a conflict."""
    authority = headless.authority
    await _deliver(authority, 'a')
    await _await_settled(authority, 'a')
    await _reset_bot_chat(authority)

    with pytest.raises(RuntimeStoreError) as exc:
        await _deliver(authority, 'b', pinned='some-other-conversation')
    assert exc.value.reason == 'admission_conflict'
