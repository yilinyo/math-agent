"""Compatibility entry for the redis task store."""
import sys
from typing import TYPE_CHECKING
from agent_platform.storage import redis as _implementation

if TYPE_CHECKING:
    from agent_platform.storage.redis import RedisTaskStore as RedisTaskStore
    from agent_platform.storage.redis import (
        _TransactionView as _TransactionView,
        decode_session as decode_session,
        decode_task as decode_task,
        encode as encode,
    )

sys.modules[__name__] = _implementation
