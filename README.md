
<p align="center">
  <img src="screenshots/logo.ico" width="96" alt="LiveIQ Viewer logo"><br>
  <b>LiveIQ Multi‑Franchisee Viewer</b><br>
  <i>Because spreadsheets are so 2020.</i>
</p>



---

## Table of Contents
1. [Why this exists](#why-this-exists)  
2. [Instant demo](#instant-demo)  
3. [What this app does](#what-this-app-does)  
4. [Quick start](#quick-start)  
5. [Packaging to .exe](#packaging-to-exe)  
6. [Working with `config.json`](#working-with-configjson)  
7. [Folder map](#folder-map)  
8. [Troubleshooting](#troubleshooting)  
9. [LiveIQ API quirks & pitfalls](#liveiq-api-quirks--pitfalls)  
10. [Developing custom modules](#developing-custom-modules)  
11. [Contributing](#contributing)  
12. [License](#license)  

---

## Why this exists
Running multiple Subway® stores often means juggling numerous LiveIQ log‑ins and exporting clunky CSVs. **This viewer** talks directly to the franchisee API, merges every store and every account into one UI, and gives you clean JSON or one‑click dashboards.

---

## Instant demo
*(Replace `screenshots/demo.gif` with a real screencast when available)*

<img src="screenshots/demo.gif" width="700" alt="animated demo">

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

## Quick start

```bash
git clone https://github.com/your-org/liveiq-viewer.git
cd liveiq-viewer
python -m venv .venv && (. .venv/bin/activate || .venv\Scripts\activate)
pip install -r requirements.txt
python liveiq_gui.py
```

First run creates **config.json** and an empty **modules/** directory.  
Fill in credentials (see below) and relaunch.

---

## Packaging to .exe

```powershell
pyinstaller --onefile --noconsole `
  --icon="logo.ico" `
  --add-data "modules;modules" `
  liveiq_gui.py
```

> `--noconsole` hides the black terminal; omit while debugging.  
> On macOS/Linux change the semicolon to a colon in `--add-data`.

---

## Working with `config.json`

```jsonc
{
  "accounts": [
    {
      "Name": "Franchisee A",
      "ClientID": "xxxxxxxx",
      "ClientKEY": "yyyyyyyy"
    }
  ]
}
```

**Location** — same folder as `liveiq_gui.py` or `liveiq_gui.exe`.

<details>
<summary><b>How to get API keys</b></summary>

1. Log into Subway Fresh Connect.  
2. **Fresh Connect ▸ Instructions** → **Generate Keys**.  
3. Copy *Client ID* & *Client KEY* into **config.json**.  

<img src="screenshots/ss-1.png" width="600" alt="generate keys">  
<img src="screenshots/ss-2.png" width="600" alt="copy keys">  
</details>

Add one object per franchisee account; duplicate store numbers are de‑duplicated automatically.

---

## Folder map
```text
liveiq-viewer/
├─ liveiq_gui.py
├─ logo.ico
├─ requirements.txt
├─ config.json
├─ error.log
└─ modules/
   ├─ daily_sales.py
   └─ daily_clockins.py
```

Packaged layout:

```
MyApp/
│ liveiq_gui.exe
│ config.json
└modules/
```

---

## Troubleshooting

| 😖 Symptom | 🩹 Fix |
|------------|-------|
| Blank window / no response | Rebuild without `--noconsole`, run EXE from *cmd* to see traceback. |
| Missing plugin buttons | Ensure `modules/` exists or include it via `--add-data`. |
| “config.json created” every launch | Edit the config next to the EXE, not the temp copy. |
| Icon refused | Provide a 256×256, 32‑bit `.ico` or let Pillow auto‑convert. |

---

## LiveIQ API quirks & pitfalls

| Issue | Impact | Mitigation |
|-------|--------|-----------|
| Undocumented rate‑limit (~60 req/min) | 429 errors | ≤10 threads, retry with back‑off. |
| Data latency (30–60 min) | “Today” may look low | Pull data after close or show warning. |
| Schema drift (`netSale` vs `netSales`) | KeyError | Always `.get()` with defaults. |
| Store‑local timestamps | Cross‑TZ math wrong | Convert with `pytz`. |
| Intermittent 500/502 | Module crash | Wrap in `try/except`, retry. |

---

## Developing custom modules

Each plugin is **one file** in *modules/*. The viewer imports it and calls `run(window)`.

<details>
<summary><b>Click for minimal example</b></summary>

```python
# modules/my_module.py
def run(win):
    import tkinter as tk, threading, datetime
    from tkinter.scrolledtext import ScrolledText
    from __main__ import fetch_data, store_vars, config_accounts

    txt = ScrolledText(win, font=("Consolas",10)); txt.pack(expand=True, fill="both")
    sel = [sid for sid,v in store_vars.items() if v.get()]
    if not sel: txt.insert("end","No stores selected."); return

    def worker():
        today = datetime.date.today().strftime("%Y-%m-%d")
        for acct in config_accounts:
            for sid in acct["StoreIDs"]:
                if sid not in sel: continue
                data = fetch_data("Sales Summary", sid, today, today,
                                  acct["ClientID"], acct["ClientKEY"])
                net = (data.get("data") or data)[0]["netSales"]
                txt.insert("end", f"{sid}: ${net}\n")
    threading.Thread(target=worker, daemon=True).start()
```
</details>

---

## Contributing
Found a bug, need a new endpoint, or have a killer module?  
[Open an issue](https://github.com/your-org/liveiq-viewer/issues) or send a PR.  
Guidelines:

1. Fork → feature branch  
2. `pip install -r requirements-dev.txt`  
3. `pre-commit install`  
4. Submit PR with screenshot / GIF for UI work.

---

## License
MIT. Do anything, just don’t blame us if your sandwich shop catches fire.

> _Built for busy Subway® franchisees who’d rather read numbers than copy‑paste them._
