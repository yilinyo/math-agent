"""Coordinate local handbook/index edits with readers across processes."""
import os
from contextlib import contextmanager
from pathlib import Path


class ResourcesBusy(Exception):
    pass


@contextmanager
def resource_lock(data_dir: Path, *, exclusive=False, blocking=True):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / '.resources.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            mode = (msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK) if exclusive else (
                msvcrt.LK_RLCK if blocking else msvcrt.LK_NBRLCK)
            try:
                msvcrt.locking(handle.fileno(), mode, 1)
            except OSError as exc:
                raise ResourcesBusy() from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            try:
                fcntl.flock(handle, mode | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise ResourcesBusy() from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def index_stamp(data_dir: Path):
    if (data_dir / '.resources-transaction.json').exists():
        raise ValueError('resource_transaction_incomplete')
    return tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in (
        data_dir / 'strategy_meta.json', data_dir / 'strategy_index.json',
        data_dir / 'strategy_lexical_manifest.json', data_dir / 'strategy_embeddings.npy',
    ) if p.is_file())
