"""One process owns the local workspace; protects restore against a running app."""
from contextlib import contextmanager
import os
import core as db

@contextmanager
def workspace_lock():
    db.DATA.mkdir(parents=True,exist_ok=True)
    handle=(db.DATA/'app.lock').open('a+b')
    handle.seek(0,os.SEEK_END)
    if handle.tell()==0:handle.write(b'0');handle.flush()
    handle.seek(0)
    acquired=False
    try:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError:
            raise RuntimeError('AutoParts is already running for this data folder. Close the running app before starting, restoring or recovering passwords.')
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()
