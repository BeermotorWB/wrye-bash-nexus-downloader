"""Download filenames: the old Nexus format Wrye Bash reads, plus Sqids.
Mirrors the Go version's TestBuildFilename / TestBuildFilenameWryeBashModID."""
import re

import pytest

from download_manager import NameParts, build_filename

# Wrye Bash's mod ID regex (Mopy/bash/bosh/__init__.py), with the extensions
# from archives.readExts.
RE_TES_NEXUS = re.compile(r"(?i)^(.*?)-(\d+)(?:-\w*)*(?:-\d+)?((\.(7z|zip|rar|001))|)$")

# Values verified against the live Nexus API on 2026-09-30.
SKSE = NameParts(name="Skyrim Script Extender (SKSE64) Steam", mod_id=30379, version="2.3.1",
                 uploaded=1787849567, uid=7318625068376, ext=".7z")


@pytest.mark.parametrize("parts, mod_id, version, want", [
    (SKSE, True, True, "Skyrim Script Extender (SKSE64) Steam-30379-2-3-1-1787849567_s6Og0dG94.7z"),
    (NameParts('a<b>c:d"e/f\\g|h?i*j', 1, "1.0", 5, 7318625068376, ".zip"), True, True,
     "a_b_c_d_e_f_g_h_i_j-1-1-0-5_s6Og0dG94.zip"),
    (NameParts("X", 2, "1.2 beta/3\\4", 5, 7318625068376, ".7z"), True, True,
     "X-2-1-2-beta-3-4-5_s6Og0dG94.7z"),
    (SKSE, False, True, "Skyrim Script Extender (SKSE64) Steam-2-3-1-1787849567_s6Og0dG94.7z"),
    (SKSE, True, False, "Skyrim Script Extender (SKSE64) Steam-30379-1787849567_s6Og0dG94.7z"),
    (NameParts("X", 2, "", 5, 7318625068376, ".7z"), True, True, "X-2-5_s6Og0dG94.7z"),
], ids=["full", "illegal chars", "version separators", "no mod ID", "no version", "empty version"])
def test_build_filename(parts, mod_id, version, want):
    assert build_filename(parts, mod_id, version) == want


@pytest.mark.parametrize("parts", [
    SKSE,
    NameParts("FSMP 4.0.1", 57339, "4.0.1", 1782605772, 7318625041304, ".7z"),
    NameParts("Foo 1.2-3 Bar", 12604, "V6-SKSE", 1782605772, 7318625041304, ".zip"),
    NameParts("Patch", 95568, "1.6b", 1770312316, 7318625041304, ".rar"),
    # a live download, 2026-09-30: POLINA FOLLOWER-193400-1-0-1790676146_cE8hkADFE.7z
    # (UID decoded from its token: game 1704, file 812140)
    NameParts("POLINA FOLLOWER", 193400, "1.0", 1790676146, 7318625084524, ".7z"),
])
def test_wrye_bash_reads_mod_id(parts):
    """The point of the old format: Wrye Bash must read the right mod ID."""
    m = RE_TES_NEXUS.search(build_filename(parts, True, True))
    assert m, "reTesNexus did not match"
    assert m.group(2) == str(parts.mod_id)


def test_polina_matches_live_name():
    """The Go build produced this exact name live; Python must too."""
    parts = NameParts("POLINA FOLLOWER", 193400, "1.0", 1790676146, 7318625084524, ".7z")
    assert build_filename(parts, True, True) == "POLINA FOLLOWER-193400-1-0-1790676146_cE8hkADFE.7z"
