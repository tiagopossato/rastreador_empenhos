import os
import errno
import time
from contextlib import contextmanager
from pathlib import Path


DEFAULT_LOCK_TIMEOUT = 300.0


def lock_path_for(index_path: Path) -> Path:
    return Path(index_path).parent.parent / ".private" / "report_update.lock"


@contextmanager
def interprocess_lock(path: Path, timeout: float = DEFAULT_LOCK_TIMEOUT):
    if timeout < 0:
        raise ValueError("O timeout do lock não pode ser negativo.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            while True:
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EDEADLK):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "Outro processo está atualizando os relatórios (timeout do lock)."
                        ) from exc
                    time.sleep(min(0.1, remaining))
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "Outro processo está atualizando os relatórios (timeout do lock)."
                        ) from exc
                    time.sleep(min(0.1, remaining))
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
