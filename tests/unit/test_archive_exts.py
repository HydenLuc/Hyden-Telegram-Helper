# SPDX-License-Identifier: AGPL-3.0-or-later
from common.constants import ARCHIVE_EXTS


def test_contains_basic_exts():
    for ext in (".zip", ".rar", ".7z"):
        assert ext in ARCHIVE_EXTS


def test_is_frozenset():
    # Immutable invariant
    assert isinstance(ARCHIVE_EXTS, frozenset)


def test_imported_consistently():
    """Both modules import the same constant from common."""
    from downloader.mover_client import ARCHIVE_EXTS as a
    from unzipper.utils import ARCHIVE_EXTS as b
    assert a is b is ARCHIVE_EXTS
