"""LiveIQ Multi-Franchisee quick-viewer (no local JSON archival)
-----------------------------------------------------------------
• Reads multiple franchisee credentials from *config.json*.
• Auto-discovers stores via /api/Restaurants.
• Lets you pick stores, a date range, and one endpoint, then streams
  JSON (pretty or flattened) in a scrollable window.
• Extensible: any *.py* in *modules/* exposing `run(window)` appears
  as a button.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set

import requests
import tkinter as tk
from tkinter import Toplevel, messagebox
from tkinter.scrolledtext import ScrolledText

# ── constants ─────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(SCRIPT_DIR, "config.json")
LOG_FILE     = os.path.join(SCRIPT_DIR, "error.log")
BASE_URL     = "https://liveiqfranchiseeapi.subway.com"

ENDPOINTS: Dict[str, str] = {
    "Sales Summary"               : "/api/SalesSummary/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
    "Daily Sales Summary"         : "/api/DailySalesSummary/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
    "Daily Timeclock"             : "/api/DailyTimeclock/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
    "Third Party Sales Summary"   : "/api/ThirdPartySalesSummary/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
    "Third Party Transaction Summary": "/api/ThirdPartyTransactionSummary/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
    "Transaction Summary"         : "/api/TransactionSummary/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
    "Transaction Details"         : "/api/TransactionDetails/{restaurantNumbers}/startDate/{startDate}/endDate/{endDate}",
}

# ── globals (populated at runtime) ────────────────────────────────────────
all_stores:         Set[str]              = set()
store_vars:         Dict[str, tk.IntVar]  = {}
account_vars:       Dict[str, tk.IntVar]  = {}
account_store_map:  Dict[str, List[str]]  = {}
config_accounts:    List[Dict[str, Any]]  = []

# ── helpers ───────────────────────────────────────────────────────────────
def log_error(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(f"[{ts}] {msg}\n")

def fetch_data(ep: str, sid: str, start: str, end: str,
               cid: str, ckey: str) -> Any:
    path = ENDPOINTS[ep].format(restaurantNumbers=sid, startDate=start, endDate=end)
    try:
        r = requests.get(
            BASE_URL + path,
            headers={"api-client": cid, "api-key": ckey, "Accept": "application/json"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:                       # noqa: BLE001
        log_error(f"Fetch error {sid} {ep}: {exc}")
        return {"error": str(exc)}

def flatten_json(obj: Any, parent: str = "", sep: str = ".") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten_json(v, f"{parent}{sep}{k}" if parent else k, sep))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten_json(v, f"{parent}[{i}]", sep))
    else:
        out[parent] = obj
    return out

# ── config bootstrap ──────────────────────────────────────────────────────
def load_config_and_stores() -> None:
    """
    Read *config.json*, auto-discover stores for each account, and populate:

        • config_accounts
        • account_store_map
        • all_stores

    If the file does not exist, a fully-filled template is written and the
    program exits so the user can add real credentials.
    """
    global config_accounts  # noqa: PLW0603

    # ── 1) ensure config.json exists ──────────────────────────────────────
    if not os.path.isfile(CONFIG_FILE):
        default_cfg = {
            "accounts": [
                {
                    "Name": "Franchisee A",
                    "ClientID": "INSERT CLIENT ID HERE",
                    "ClientKEY": "INSERT CLIENT KEY HERE",
                },
                {
                    "Name": "Franchisee B",
                    "ClientID": "INSERT CLIENT ID HERE",
                    "ClientKEY": "INSERT CLIENT KEY HERE",
                },
                {
                    "Name": "Franchisee C",
                    "ClientID": "INSERT CLIENT ID HERE",
                    "ClientKEY": "INSERT CLIENT KEY HERE",
                },
            ]
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(default_cfg, fh, indent=2)
        messagebox.showinfo(
            "Config Created",
            f"A starter {os.path.basename(CONFIG_FILE)} has been created.\n"
            "Please add your LiveIQ credentials and relaunch the app.",
        )
        raise SystemExit

    # ── 2) load and validate ─────────────────────────────────────────────
    with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    for acct in cfg.get("accounts", []):
        if not all(k in acct for k in ("Name", "ClientID", "ClientKEY")):
            log_error(f"Malformed account entry: {acct}")
            continue

        acct["Status"] = "ERROR"          # pessimistic default

        # ── 3) fetch store list for this account ─────────────────────────
        try:
            res = requests.get(
                BASE_URL + "/api/Restaurants",
                headers={
                    "api-client": acct["ClientID"],
                    "api-key": acct["ClientKEY"],
                    "Accept": "application/json",
                },
                timeout=10,
            )
            res.raise_for_status()
            stores = [
                r["restaurantNumber"]
                for r in res.json()
                if "restaurantNumber" in r
            ]
            acct["StoreIDs"] = stores
            acct["Status"]   = "OK" if stores else "EMPTY"
            account_store_map[acct["Name"]] = stores
            all_stores.update(stores)
        except Exception as exc:          # noqa: BLE001
            log_error(f"{acct['Name']} store fetch failed: {exc}")

    # ── 4) expose full list to rest of program ───────────────────────────
    config_accounts[:] = cfg.get("accounts", [])


# ── external-module loader ────────────────────────────────────────────────
def load_external_modules(root: tk.Tk) -> None:
    mod_dir = os.path.join(SCRIPT_DIR, "modules")
    # NEW: auto-create folder if missing, then exit quietly
    if not os.path.isdir(mod_dir):
        os.makedirs(mod_dir, exist_ok=True)
        return
    
    frame = tk.Frame(root); frame.pack(pady=10)
    row = col = 0
    for path in glob.glob(os.path.join(mod_dir, "*.py")):
        name = os.path.splitext(os.path.basename(path))[0]

        def _cb(p=path, n=name):
            def _():
                try:
                    win = Toplevel(root); win.title(n.capitalize()); win.geometry("800x600")
                    spec = importlib.util.spec_from_file_location(n, p)
                    mod  = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)                      # type: ignore[attr-defined]
                    if hasattr(mod, "run") and callable(mod.run):
                        mod.run(win)
                    else:
                        tk.Label(win, text=f"{n} lacks run(window)", fg="red").pack(pady=40)
                except Exception as exc:                              # noqa: BLE001
                    log_error(f"Module load {n}: {exc}")
                    messagebox.showerror("Module Error", str(exc))
            return _

        tk.Button(frame, text=name.capitalize(), command=_cb(),
                  font=("Arial", 12), bg="#007ACC", fg="white"
        ).grid(row=row, column=col, padx=10, pady=5, sticky="w")

        col = (col + 1) % 4
        if col == 0:
            row += 1

# ── viewer window ─────────────────────────────────────────────────────────
def open_view_window(endpoint: str, stores: List[str],
                     start: str, end: str) -> None:
    win = Toplevel(); win.title(f"View – {endpoint}"); win.geometry("900x650")

    toolbar = tk.Frame(win); toolbar.pack(fill="x", pady=4)
    flat_var = tk.IntVar(value=0)
    tk.Checkbutton(toolbar, text="Flatten", variable=flat_var).pack(side="left", padx=6)
    copy_btn = tk.Button(toolbar, text="Copy All", state=tk.DISABLED); copy_btn.pack(side="right", padx=6)

    txt = ScrolledText(win, wrap="word", font=("Consolas", 10))
    txt.pack(expand=True, fill="both", padx=10, pady=10)

    def write(l=""):
        txt.insert("end", l + "\n"); txt.see("end")

    write(f"Endpoint: {endpoint}")
    write(f"Range   : {start} → {end}")
    write(f"Stores  : {', '.join(stores)}\n")

    futures: Dict[Any, Any] = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        fetched = set()
        for acct in config_accounts:
            cid, ckey, aname = acct["ClientID"], acct["ClientKEY"], acct["Name"]
            for sid in acct.get("StoreIDs", []):
                if sid in stores and sid not in fetched:
                    fut = ex.submit(fetch_data, endpoint, sid, start, end, cid, ckey)
                    futures[fut] = (aname, sid); fetched.add(sid)

        for fut in as_completed(futures):
            aname, sid = futures[fut]; res = fut.result()
            write(f"\n### {aname} – Store {sid} ###")
            if "error" in res:
                write(f"ERROR: {res['error']}"); continue

            payload = res.get("data", res)
            if flat_var.get():
                iterable = payload if isinstance(payload, list) else [payload]
                for idx, entry in enumerate(iterable, 1):
                    write(f"— Entry {idx} —")
                    for k, v in flatten_json(entry).items():
                        write(f"{k:40} : {v}")
            else:
                write(json.dumps(payload, indent=2, ensure_ascii=False))

    def copy_all() -> None:
        win.clipboard_clear(); win.clipboard_append(txt.get("1.0", "end-1c"))
    copy_btn.config(state=tk.NORMAL, command=copy_all)

# ── date-range helper ─────────────────────────────────────────────────────
def update_dates(option: str, start_e: tk.Entry, end_e: tk.Entry) -> None:
    today = datetime.now().date()
    if option == "Custom":
        return
    if option == "Today":
        start = end = today
    elif option == "Yesterday":
        start = end = today - timedelta(days=1)
    elif option.startswith("Past"):
        days  = int(option.split()[1])
        end   = today - timedelta(days=1)
        start = end - timedelta(days=days - 1)
    else:
        return
    for e, val in ((start_e, start), (end_e, end)):
        e.delete(0, "end"); e.insert(0, str(val))

# ── main GUI ──────────────────────────────────────────────────────────────
def build_gui() -> None:
    root = tk.Tk(); root.title("LiveIQ Multi-Franchisee Tool"); root.geometry("960x800")
    try:
        load_config_and_stores()
    except SystemExit:
        root.destroy(); return

    # --- ACCOUNTS section --------------------------------------------------
    acct_hdr = tk.Frame(root); acct_hdr.pack(pady=(10,0), fill="x")
    acct_hdr.grid_columnconfigure((0,1,2), weight=1)

    def acct_select_all()   -> None: [v.set(1) for v in account_vars.values()]
    def acct_unselect_all() -> None: [v.set(0) for v in account_vars.values()]

    tk.Button(acct_hdr, text="Select All",   command=acct_select_all   ).grid(row=0, column=0, sticky="e")
    tk.Label (acct_hdr, text="Accounts", font=("Arial", 16)).grid(row=0, column=1)
    tk.Button(acct_hdr, text="Unselect All", command=acct_unselect_all ).grid(row=0, column=2, sticky="w")

    acct_frame = tk.Frame(root); acct_frame.pack()
    for idx, acct in enumerate(config_accounts):
        name = acct["Name"]; status = acct["Status"]
        var  = tk.IntVar(value=1 if status=="OK" else 0); account_vars[name]=var
        fg   = "black" if status=="OK" else "red"
        state= tk.NORMAL if status=="OK" else tk.DISABLED

        def cascade(n=name, v=var):
            for st in account_store_map.get(n, []):
                if st in store_vars: store_vars[st].set(v.get())

        tk.Checkbutton(acct_frame, text=name, variable=var, fg=fg,
                       state=state, command=cascade
        ).grid(row=idx//4, column=idx%4, padx=10, pady=5, sticky="w")

    # --- STORES section ----------------------------------------------------
    store_hdr = tk.Frame(root); store_hdr.pack(pady=(20,5), fill="x")
    store_hdr.grid_columnconfigure((0,1,2), weight=1)
    def store_select_all()   -> None: [v.set(1) for v in store_vars.values()]
    def store_unselect_all() -> None: [v.set(0) for v in store_vars.values()]
    tk.Button(store_hdr, text="Select All",   command=store_select_all   ).grid(row=0,column=0, sticky="e")
    tk.Label (store_hdr, text="Stores", font=("Arial", 16)).grid(row=0,column=1)
    tk.Button(store_hdr, text="Unselect All", command=store_unselect_all ).grid(row=0,column=2, sticky="w")

    store_frame = tk.Frame(root); store_frame.pack()
    for idx, sid in enumerate(sorted(all_stores, key=int)):
        var = tk.IntVar(value=1); store_vars[sid]=var
        tk.Checkbutton(store_frame, text=sid, variable=var
        ).grid(row=idx//6, column=idx%6, padx=8, pady=4, sticky="w")

    # --- DATE range --------------------------------------------------------
    date_frame = tk.Frame(root); date_frame.pack(pady=15)
    tk.Label(date_frame, text="Start Date:").grid(row=0,column=0,padx=5)
    start_entry = tk.Entry(date_frame); start_entry.grid(row=0,column=1,padx=5)
    tk.Label(date_frame, text="End Date:").grid(row=0,column=2,padx=5)
    end_entry   = tk.Entry(date_frame);   end_entry.grid(row=0,column=3,padx=5)
    today = datetime.now().date(); start_entry.insert(0, str(today)); end_entry.insert(0,str(today))

    range_var = tk.StringVar(value="Today")
    start_entry.bind("<KeyRelease>", lambda e: range_var.set("Custom"))
    end_entry  .bind("<KeyRelease>", lambda e: range_var.set("Custom"))

    opts = ["Custom","Today","Yesterday","Past 2 Days","Past 3 Days",
            "Past 7 Days","Past 14 Days","Past 30 Days"]
    opts_frame = tk.Frame(root); opts_frame.pack()
    for idx, val in enumerate(opts):
        tk.Radiobutton(opts_frame, text=val, variable=range_var, value=val,
                       command=lambda v=val: update_dates(v,start_entry,end_entry)
        ).grid(row=idx//4, column=idx%4, padx=10, pady=5, sticky="w")

    # --- ENDPOINT + VIEW ---------------------------------------------------
    ep_frame = tk.Frame(root); ep_frame.pack(pady=10)
    tk.Label(ep_frame, text="Endpoint:", font=("Arial",12)).pack(side="left", padx=5)
    endpoint_var = tk.StringVar(value=list(ENDPOINTS.keys())[0])
    tk.OptionMenu(ep_frame, endpoint_var, *ENDPOINTS.keys()).pack(side="left", padx=5)

    tk.Button(ep_frame, text="View",
              command=lambda: open_view_window(
                  endpoint_var.get(),
                  [s for s,v in store_vars.items() if v.get()],
                  start_entry.get(), end_entry.get()
              )
    ).pack(side="left", padx=10)

    # --- External modules --------------------------------------------------
    load_external_modules(root)
    root.mainloop()

# ── entry-point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    build_gui()
