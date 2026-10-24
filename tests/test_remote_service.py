from __future__ import annotations

import stat as statmod
from types import SimpleNamespace

from backend.remote.service import RemoteEntry, SFTPSession


class _FakeSftp:
    def __init__(self, attr):
        self.attr = attr
        self.stat_called = False

    def lstat(self, path):
        assert path == "/link"
        return self.attr

    def stat(self, path):
        self.stat_called = True
        raise AssertionError("stat() must not be used for symlink-safe SFTP metadata")


def test_sftp_stat_uses_lstat_and_reports_symlink():
    attr = SimpleNamespace(
        st_mode=statmod.S_IFLNK | 0o777,
        st_size=12,
        st_mtime=1,
    )
    fake = _FakeSftp(attr)
    session = SFTPSession({})
    session.sftp = fake

    entry = session.stat("/link")

    assert entry.path == "/link"
    assert entry.is_symlink is True
    assert entry.is_dir is False
    assert fake.stat_called is False


class _WalkSession:
    def stat(self, path):
        return RemoteEntry("root", "/root", True, 0, None)

    def listdir(self, path):
        if path == "/root":
            return [
                RemoteEntry("real", "/root/real", True, 0, None),
                RemoteEntry("linked-dir", "/root/linked-dir", False, 0, None, True),
                RemoteEntry("file.bin", "/root/file.bin", False, 10, None),
            ]
        if path == "/root/real":
            return [RemoteEntry("inside.bin", "/root/real/inside.bin", False, 20, None)]
        raise AssertionError(path)


def test_remote_walk_skips_symlinks():
    directories, files = SFTPSession.walk(_WalkSession(), "/root")

    assert directories == ["", "real"]
    assert files == [("file.bin", 10), ("real/inside.bin", 20)]
