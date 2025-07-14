# LiveIQ Multi-Franchisee Viewer
*A Tkinter desktop tool for Subway® LiveIQ data*

---

## Table of Contents
1. [What this app does](#what-this-app-does)  
2. [Quick start (Python script)](#quick-start-python-script)  
3. [Building a standalone .exe](#building-a-standalone-exe)  
4. [Working with `config.json`](#working-with-configjson)  
5. [Folder map](#folder-map)  
6. [Troubleshooting](#troubleshooting)  
7. [Developing custom modules](#developing-custom-modules)  

---

## What this app does
| 🛠 Feature | Detail |
|-----------|--------|
| **Multi‑account login** | Reads unlimited `ClientID` / `ClientKEY` pairs from *config.json* and auto‑discovers every store each account controls. |
| **Store & account filters** | Checkbox grids with “Select All / Unselect All” for both accounts **and** stores. Account check/uncheck cascades to its stores. |
| **Date presets** | Today • Yesterday • Past N Days (2‑30) or custom. |
| **Endpoint picker** | 7 built‑in LiveIQ endpoints (add more by editing a dict). |
| **Viewer** | Pretty‑printed JSON *or* flattened key‑value view, plus “Copy All” to clipboard. |
| **Module system** | Drop a `*.py` file in `modules/` and it appears as a button—build custom pop‑up tools in minutes. |
| **Error logging** | UTC‑stamped `error.log` beside the app. |
| **Packaging‑friendly** | Works as `python liveiq_gui.py` **or** a PyInstaller `--onefile` EXE. Config & modules live next to the EXE so users can edit them. |

---

## Quick start (Python script)

```bash
git clone https://github.com/your-org/liveiq-viewer.git
cd liveiq-viewer

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python liveiq_gui.py
```

First launch creates **config.json** and (if absent) **modules/**.  
Fill in credentials (see below) and rerun.

---

## Building a standalone .exe

> **Prerequisites:** Windows, Python 3.8–3.12, and `pip install pyinstaller pillow`.

```powershell
pyinstaller --onefile --noconsole ^
  --icon="logo.ico" ^
  --add-data "modules;modules" ^
  liveiq_gui.py
```

*On macOS/Linux change the semicolon to a colon in `--add-data`.*

---

## Working with `config.json`

```jsonc
{
  "accounts": [
    {
      "Name": "Franchisee A",
      "ClientID": "xxxxxxxx",
      "ClientKEY": "yyyyyyyy"
    },
    {
      "Name": "Franchisee B",
      "ClientID": "xxxxxxxx",
      "ClientKEY": "yyyyyyyy"
    }
  ]
}
```

*Location –* same folder as `liveiq_gui.py` or the EXE.

### Add / edit accounts
1. Open **config.json** in a text editor.  
2. Duplicate an object or edit values.  
3. Save and relaunch—new accounts appear automatically.

---

## Folder map

```
liveiq-viewer/
│ liveiq_gui.py
│ requirements.txt
│ logo.ico
│ config.json         # user credentials (created first run)
│ error.log           # generated at runtime
└modules/
   ├ daily_sales.py
   └ daily_clockins.py
```

Packaged (`--onefile`) layout:

```
MyApp/
│ liveiq_gui.exe
│ config.json
└modules/             # user overrides (optional)
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| **Blank window / no response** | Rebuild without `--noconsole` and run EXE from *cmd* to read traceback. |
| **No module buttons** | Ensure `modules/` exists beside the EXE *or* rebuild with `--add-data "modules;modules"`. |
| **“config.json created” every launch** | Edit the config that lives next to the EXE, not one in Temp. |
| **Icon error in PyInstaller** | Provide a true 256 × 256 32‑bit `.ico` or install Pillow for auto‑conversion. |

---

## Developing custom modules

Modules live in **modules/**. Each file becomes a button at runtime.

### 1  Minimal template

```python
# modules/my_module.py
def run(window):
    """window is a fresh Tkinter *Toplevel*."""
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText
    from datetime import date
    from __main__ import fetch_data, store_vars, config_accounts

    window.title("My Module")
    window.geometry("600x400")
    out = ScrolledText(window, font=("Consolas", 10))
    out.pack(expand=True, fill="both")

    selected = [sid for sid, v in store_vars.items() if v.get()]
    if not selected:
        out.insert("end", "No stores selected."); return

    today = date.today().strftime("%Y-%m-%d")
    for acct in config_accounts:
        cid, ckey = acct["ClientID"], acct["ClientKEY"]
        for sid in acct["StoreIDs"]:
            if sid not in selected: continue
            data = fetch_data("Sales Summary", sid, today, today, cid, ckey)
            net  = (data.get("data") or data)[0]["netSales"]
            out.insert("end", f"Store {sid}: ${net}\n")
```

### 2  Host helpers

| Name | Use |
|------|-----|
| `fetch_data(endpoint, store_id, start, end, cid, ckey)` | LiveIQ API wrapper (returns JSON or `{"error": …}`) |
| `store_vars` | `{store_id: tk.IntVar}` – see which stores are ticked |
| `config_accounts` | list of account dicts (each has `StoreIDs`, `Status`) |
| `account_store_map` | `{account_name: [stores]}` |
| `flatten_json(obj)` | Turns nested JSON into dotted-path dict |
| `log_error(msg)` | Append to `error.log` |

### 3  Endpoint keys

Value for the first arg of `fetch_data()` must match a key in `ENDPOINTS`:

- `"Sales Summary"`
- `"Daily Sales Summary"`
- `"Daily Timeclock"`
- `"Third Party Sales Summary"`
- `"Third Party Transaction Summary"`
- `"Transaction Summary"`
- `"Transaction Details"`

Add more by editing `ENDPOINTS` in **liveiq_gui.py**.

### 4  Debug & best‑practice tips

* Import heavy libs **inside `run()`** → smoother PyInstaller builds.  
* Use `threading.Thread(..., daemon=True)` for long‑running tasks.  
* Write errors to `log_error()`; read **error.log** if something fails.  
* Ship demo modules with the app by keeping them in *modules/* and bundling the folder (`--add-data`). Users can override by adding files to their own modules folder next to the EXE.

---

Happy hacking—open an issue or PR if you build a cool new report!
