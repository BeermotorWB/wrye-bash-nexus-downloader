"""The Waiting row a link shows while Nexus answers."""
from types import SimpleNamespace

import api as api_module
from api import Api
from config import Config
from download_manager import State
from nxm_parser import parse_nxm


def make_api(tmp_path, monkeypatch):
    errors = []
    a = Api(Config(api_key="test-key", download_dir=str(tmp_path)), [])
    monkeypatch.setattr(a, "_emit_error", errors.append)
    monkeypatch.setattr(a, "_show_and_focus", lambda: None)
    return a, errors


def test_waiting_row_removed_when_nexus_answers(tmp_path, monkeypatch):
    a, _ = make_api(tmp_path, monkeypatch)
    stop = a._show_waiting("skyrimspecialedition mod 30379, file 795992")

    items = a._dl_mgr.items()
    assert [i.state for i in items] == [State.WAITING]
    assert items[0].progress()["status"] == "Waiting"
    assert items[0].file_name == "Waiting for: skyrimspecialedition mod 30379, file 795992"
    a._dl_mgr.clear_completed()
    assert len(a._dl_mgr.items()) == 1  # Clear All Completed keeps it

    assert stop() is False
    assert a._dl_mgr.items() == []
    assert stop() is False  # a second call is harmless


def test_waiting_row_cancelled(tmp_path, monkeypatch):
    a, _ = make_api(tmp_path, monkeypatch)
    stop = a._show_waiting("Collection 62eesj, revision 7")
    id = a._dl_mgr.items()[0].id

    a._dl_mgr.cancel(id)
    assert stop() is True
    assert [i.state for i in a._dl_mgr.items()] == [State.CANCELLED]
    a._dl_mgr.delete(id)  # never downloaded: no files to touch
    assert a._dl_mgr.items() == []


class FakeClient:
    """file_details runs `during` (the user acting while Nexus is slow), then
    fails or answers."""
    during = None
    fail = False

    def __init__(self, api_key):
        pass

    def file_details(self, domain, mod_id, file_id):
        FakeClient.during()
        if FakeClient.fail:
            raise RuntimeError("Nexus API Error 503: down")
        return SimpleNamespace(file_name="SKSE.7z", uid=1, size_in_bytes=5)

    def generate_download_link(self, *args):
        return [SimpleNamespace(uri="https://cdn.example/x")]


LINK = "nxm://skyrimspecialedition/mods/30379/files/795992"


def test_cancelled_link_gets_no_dialog_or_error(tmp_path, monkeypatch):
    a, errors = make_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api_module, "NexusClient", FakeClient)
    dialogs = []
    monkeypatch.setattr(a, "_save_dialog", lambda name: dialogs.append(name) or "")

    for fail in (False, True):
        FakeClient.fail = fail
        FakeClient.during = lambda: a._dl_mgr.cancel(a._dl_mgr.items()[-1].id)
        a._start_nxm_download(parse_nxm(LINK))

    assert dialogs == [] and errors == []
    assert [i.state for i in a._dl_mgr.items()] == [State.CANCELLED, State.CANCELLED]


def test_waiting_row_gone_before_dialog(tmp_path, monkeypatch):
    a, errors = make_api(tmp_path, monkeypatch)
    monkeypatch.setattr(api_module, "NexusClient", FakeClient)
    rows_at_dialog = []
    monkeypatch.setattr(a, "_save_dialog",
                        lambda name: rows_at_dialog.append(len(a._dl_mgr.items())) or "")
    seen = []
    FakeClient.fail = False
    FakeClient.during = lambda: seen.append([i.state for i in a._dl_mgr.items()])

    a._start_nxm_download(parse_nxm(LINK))

    assert seen == [[State.WAITING]]  # shown while Nexus answers
    assert rows_at_dialog == [0]  # gone once it has
    assert errors == []

    FakeClient.fail = True
    a._start_nxm_download(parse_nxm(LINK))
    assert errors == ["Download error: Nexus API Error 503: down"]
    assert a._dl_mgr.items() == []
