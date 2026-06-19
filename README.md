# Wrye Bash Nexus Downloader

A standalone Windows GUI application that handles `nxm://` and `modl://` (MO2) protocol links from the browser and downloads mod files from Nexus Mods, naming them according to Wrye Bash conventions. Built with [pywebview](https://pywebview.flowrl.com/) (Python + WebView2) with system tray support.

This is the preview of the NXM download handler for Wrye Bash >316 NexusMods integrations. 

Windows requires that protocol handlers called from web browsers be executables, et voila.

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

`seven_zip_path` is optional — leave blank to auto-detect `7z.exe` from PATH or the Wrye Bash installation.

## License

[GNU General Public License v3.0](LICENSE)
