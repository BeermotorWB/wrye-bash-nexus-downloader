# Wrye Bash Nexus Downloader (Python Port)

A standalone Windows GUI application that handles `nxm://` and `modl://` (MO2) protocol links from the browser and downloads mod files from Nexus Mods, naming them according to Wrye Bash conventions. Built with [pywebview](https://pywebview.flowrl.com/) (Python + WebView2) with system tray support.

> **⚠️ This is a mostly untested Python port of the [Go/Wails original](https://github.com/BeermotorWB/wrye-bash-nexus-downloader). Use at your own risk. No support is provided.**

## Prerequisites

- Python 3.11+
- Windows 10 1809+ / Windows 11

## Build

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pyinstaller build.spec --noconfirm
```

Output: `dist/Wrye Bash Nexus Downloader.exe`

## Usage

```
# Register as nxm:// handler (per-user, no admin)
"Wrye Bash Nexus Downloader.exe" --register

# Deregister
"Wrye Bash Nexus Downloader.exe" --deregister

# Register as modl:// handler (MO2 direct downloads)
"Wrye Bash Nexus Downloader.exe" --register-modl

# Deregister modl://
"Wrye Bash Nexus Downloader.exe" --deregister-modl

# Handle an NXM link (browser invocation)
"Wrye Bash Nexus Downloader.exe" "nxm://skyrimspecialedition/mods/12604/files/12345?key=xxx&expires=yyy"

# Handle a MODL link (MO2 direct download, no API key needed)
"Wrye Bash Nexus Downloader.exe" "modl://skyrimspecialedition/?url=https://..."
```

When launched without arguments, the app opens the main GUI window. It runs as a single instance — subsequent launches with an NXM link forward the link to the running instance via IPC.

## Architecture

```
main.py                  Entrypoint (argv parsing, single-instance, webview bootstrap)
config.py                JSON config read/write
nxm_parser.py            NXM URL parser (mods + collections)
modl_parser.py           MODL URL parser (MO2 direct downloads)
nexus_client.py          Nexus Mods v1 API + GraphQL client (collections)
download_manager.py      Download manager (streaming, pause/resume/cancel)
archive.py               7z extraction wrapper (used for collection archives)
instance.py              Single-instance gate (mutex + IPC)
registry.py              Windows registry for nxm:// and modl:// protocols
tray.py                  System tray integration
focus.py                 Window focus helpers (Windows-specific)
api.py                   JS bridge (wires downloads + IPC + UI)
frontend/
  index.html             Main UI
  app.js                 Frontend logic
  style.css              Styling (dark/light theme)
icons/                   Application icons
```

## Config

Stored in `wb_nxm_downloader.json` next to the executable (compatible with the Go version):

```json
{
  "api_key": "your-nexus-api-key",
  "download_dir": "C:\\path\\to\\downloads",
  "minimize_to_tray": true,
  "append_mod_id": true,
  "append_version": true,
  "seven_zip_path": ""
}
```

`seven_zip_path` is optional — leave blank to auto-detect `7z.exe` from PATH or the Wrye Bash installation. Required only for Collections downloads.

## License

[GNU General Public License v3.0](LICENSE)
