from __future__ import annotations

import os

from clawcodex_ext.utils import file_lock


def test_exclusive_file_lock_uses_windows_byte_lock(monkeypatch, tmp_path) -> None:
    calls = []

    class FakeMsvcrt:
        LK_LOCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(fd: int, mode: int, length: int) -> None:
            calls.append((mode, length, os.lseek(fd, 0, os.SEEK_CUR)))

    monkeypatch.setattr(file_lock, "_msvcrt", FakeMsvcrt)

    with file_lock.exclusive_file_lock(tmp_path / "catalog.lock") as fd:
        assert fd >= 0

    assert calls == [(FakeMsvcrt.LK_LOCK, 1, 0), (FakeMsvcrt.LK_UNLCK, 1, 0)]
