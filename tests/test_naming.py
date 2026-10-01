"""Download filenames: Nexus's own file_name, with Windows-illegal characters
replaced. Mirrors the Go version's TestSafeFilename."""
import pytest

from download_manager import safe_filename


@pytest.mark.parametrize("name, want", [
    # Nexus's file_name is kept as it is
    ("Example Mod 12345 1.2.3 2026-08-27T16-52Z s6Og0dG94.7z",
     "Example Mod 12345 1.2.3 2026-08-27T16-52Z s6Og0dG94.7z"),
    ("Example Mod-12345-1-2-3-1787849567.zip", "Example Mod-12345-1-2-3-1787849567.zip"),
    # characters Windows forbids in file names become "_"
    ('a<b>c:d"e/f\\g|h?i*j.7z', "a_b_c_d_e_f_g_h_i_j.7z"),
], ids=["new format", "old format", "illegal chars"])
def test_safe_filename(name, want):
    assert safe_filename(name) == want
