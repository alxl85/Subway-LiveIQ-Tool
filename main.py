"""Subway-LiveIQ-Tool
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
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set
import random, string
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

# ── date globals (for modules) ───────────────────────────────────────────
start_entry: tk.Entry
end_entry:   tk.Entry

def get_selected_start_date() -> str:
    return start_entry.get()

def get_selected_end_date() -> str:
    return end_entry.get()

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
    if not os.path.isdir(mod_dir):
        os.makedirs(mod_dir, exist_ok=True)
        return

    frame = tk.Frame(root)
    frame.grid(row=7, column=0, pady=(10,0), sticky="n")
    row = col = 0
    for path in glob.glob(os.path.join(mod_dir, "*.py")):
        name = os.path.splitext(os.path.basename(path))[0]
        def _cb(p=path, n=name):
            def _():
                win = Toplevel(root)
                win.title(n.capitalize()); win.geometry("800x600")
                # … same module-loading …
            return _
        tk.Button(frame, text=name.capitalize(), command=_cb(),
                  font=("Arial", 12), bg="#007ACC", fg="white")\
          .grid(row=row, column=col, padx=8, pady=5)
        col = (col+1)%4
        if col==0: row+=1

# ── viewer window ─────────────────────────────────────────────────────────
def open_view_window(endpoint: str, stores: List[str],
                     start: str, end: str) -> None:
    win = Toplevel(); win.title(f"View – {endpoint}"); win.geometry("800x600")

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



class ToolTip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text   = text
        self.delay  = delay
        self.id     = None
        self.tw     = None
        self.x = self.y = 0

        # use add='+' so these don't clobber other <Enter>/<Leave> bindings
        widget.bind("<Enter>",       self._on_enter,  add='+')
        widget.bind("<Leave>",       self._on_leave,  add='+')
        widget.bind("<Motion>",      self._on_motion, add='+')
        widget.bind("<ButtonPress>", self._on_leave,  add='+')

    def _on_enter(self, event=None):
        self._schedule()

    def _on_motion(self, event):
        # track where the cursor is
        self.x, self.y = event.x_root, event.y_root

    def _on_leave(self, event=None):
        self._unschedule()

    def _schedule(self):
        self._unschedule()
        self.id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        self._hide_tip()

    def _show(self):
        if self.tw:
            return
        # position it just below/right of the cursor
        x = self.x + 10
        y = self.y + 10
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tw, text=self.text, justify="left",
            background="#ffffe0", relief="solid", borderwidth=1,
            font=("Arial", "10", "normal")
        )
        label.pack(ipadx=4, ipady=2)

    def _hide_tip(self):
        if self.tw:
            self.tw.destroy()
            self.tw = None


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, height=200, **kwargs):
        super().__init__(parent, **kwargs)

        # ── canvas + scrollbar ──────────────────────────────────
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, height=height)
        self.vsb    = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # ── interior frame ───────────────────────────────────────
        self.inner = tk.Frame(self.canvas)
        # keep the window ID so we can resize it later:
        self._inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        # whenever the canvas itself is resized, stretch the inner window to match
        self.canvas.bind("<Configure>", self._on_canvas_configure, add='+')

        # track the contents resizing to update scrollregion
        self.inner.bind("<Configure>", self._on_inner_configure, add='+')

        # mouse-wheel binding (unchanged)
        for widget in (self.canvas, self.vsb, self.inner):
            widget.bind("<Enter>",    self._bind_mousewheel,   add='+')
            widget.bind("<Leave>",    self._unbind_mousewheel, add='+')

    def _on_canvas_configure(self, event):
        # force the inner window item to exactly canvas width
        self.canvas.itemconfigure(self._inner_id, width=event.width)

    def _on_inner_configure(self, event):
        # update scrollregion to match new inner size
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        # bind children for mousewheel...
        for child in self.inner.winfo_children():
            if not getattr(child, "_mw_bound", False):
                child.bind("<Enter>",    self._bind_mousewheel,   add='+')
                child.bind("<Leave>",    self._unbind_mousewheel, add='+')
                child._mw_bound = True

    def _bind_mousewheel(self, event):
        # whenever the pointer enters canvas/inner/scrollbar/child, bind wheel events
        target = event.widget
        if sys.platform == 'darwin':
            target.bind("<MouseWheel>", self._on_mousewheel, add='+')
        else:
            target.bind("<MouseWheel>", self._on_mousewheel, add='+')
            target.bind("<Button-4>",   self._on_mousewheel, add='+')
            target.bind("<Button-5>",   self._on_mousewheel, add='+')

    def _unbind_mousewheel(self, event):
        # when the pointer leaves, unbind them again
        target = event.widget
        if sys.platform == 'darwin':
            target.unbind("<MouseWheel>")
        else:
            target.unbind("<MouseWheel>")
            target.unbind("<Button-4>")
            target.unbind("<Button-5>")

    def _on_mousewheel(self, event):
        # normalize delta and scroll the canvas
        if event.delta:  # Windows / macOS
            move = int(-1 * (event.delta / 120))
        else:            # Linux: Button-4/5
            move = -1 if event.num == 5 else 1
        self.canvas.yview_scroll(move, "units")


def debug_generate_data(
    master: tk.Misc,
    num_accounts: int = 10,
    stores_per_account: int = 10,
    store_id_digits: int = 6,
    failure_rate: float = 0.25,
):
    """
    Populate globals with fake accounts and stores, simulating some API-key failures.
    Call this right after `root = tk.Tk()` within build_gui().
    """
    global config_accounts, account_store_map, all_stores
    account_vars.clear()
    store_vars.clear()
    config_accounts.clear()
    account_store_map.clear()
    all_stores.clear()

    for ai in range(1, num_accounts + 1):
        name = f"Acct_{ai}"
        cid  = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        ckey = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

        # decide if this account "fails"
        if random.random() < failure_rate:
            status = "ERROR"
            stores = []
        else:
            status = "OK"
            # generate unique store IDs
            stores = {
                str(random.randint(10**(store_id_digits-1),
                                  10**store_id_digits-1))
                for _ in range(stores_per_account)
            }

        config_accounts.append({
            "Name":       name,
            "ClientID":   cid,
            "ClientKEY":  ckey,
            "Status":     status,
            "StoreIDs":   list(stores),
        })
        account_store_map[name] = list(stores)
        all_stores.update(stores)

    # now initialize the IntVars _with_ a master, disabling errors
    for acct in config_accounts:
        account_vars[acct["Name"]] = tk.IntVar(
            master=master,
            value=1 if acct["Status"] == "OK" else 0
        )

    # and stores
    for sid in sorted(all_stores, key=int):
        store_vars[sid] = tk.IntVar(master=master, value=1)


# ── main GUI ──────────────────────────────────────────────────────────────
def build_gui() -> None:
    global start_entry, end_entry

    root = tk.Tk()
    root.title("Subway-LiveIQ-Tool")
    root.geometry("800x600")
    root.resizable(False, False)

    # ── DEBUG SEED ─────────────────────────────────────────────────
    DEBUG = False
    if DEBUG:
        debug_generate_data(root, num_accounts=20, stores_per_account=10)
    else:
        try:
            load_config_and_stores()
        except SystemExit:
            root.destroy()
            return

        # initialize our IntVars for real accounts & stores
        for acct in config_accounts:
            account_vars[acct["Name"]] = tk.IntVar(
                master=root,
                value=1 if acct["Status"] == "OK" else 0
            )
        for sid in sorted(all_stores, key=int):
            store_vars[sid] = tk.IntVar(master=root, value=1)
    # ────────────────────────────────────────────────────────────────

    root.grid_columnconfigure(0, weight=1)

    # --- ACCOUNTS header row ---
    def acct_select_all():
        for v in account_vars.values():
            v.set(1)
        for v in store_vars.values():
            v.set(1)

    def acct_unselect_all():
        for v in account_vars.values():
            v.set(0)
        for v in store_vars.values():
            v.set(0)

    acct_hdr = tk.Frame(root)
    acct_hdr.grid(row=0, column=0, sticky="ew", pady=(10,5))
    acct_hdr.grid_columnconfigure((0,1,2), weight=1)

    tk.Button(acct_hdr, text="Select All", command=acct_select_all)\
      .grid(row=0, column=0, sticky="e")
    tk.Label(acct_hdr, text="Accounts", font=("Arial",16))\
      .grid(row=0, column=1)
    tk.Button(acct_hdr, text="Unselect All", command=acct_unselect_all)\
      .grid(row=0, column=2, sticky="w")

    # --- ACCOUNTS list with generic LOGIN labels + tooltips ---
    ACC_COLS = 10
    acct_frame = ScrollableFrame(root, height=75)
    acct_frame.grid(row=1, column=0, sticky="ew", padx=12)
    for c in range(ACC_COLS):
        acct_frame.inner.grid_columnconfigure(c, weight=1)

    rows = [
        config_accounts[i:i+ACC_COLS]
        for i in range(0, len(config_accounts), ACC_COLS)
    ]
    for r, row_items in enumerate(rows):
        offset = (ACC_COLS - len(row_items)) // 2
        for c, acct in enumerate(row_items):
            real_name = acct["Name"]
            login_lbl = f"API #{r*ACC_COLS + c + 1}"
            var       = account_vars[real_name]

            cb = tk.Checkbutton(
                acct_frame.inner,
                text=login_lbl,
                variable=var,
                fg="black" if acct["Status"]=="OK" else "red",
                state=(tk.NORMAL if acct["Status"]=="OK" else tk.DISABLED),
                command=lambda n=real_name, v=var: [
                    store_vars[s].set(v.get())
                    for s in account_store_map.get(n, [])
                    if s in store_vars
                ]
            )
            cb.grid(row=r, column=c + offset, padx=6, pady=4, sticky="n")
            ToolTip(cb, real_name)

    # --- STORES header ---
    def store_select_all():
        for v in store_vars.values():
            v.set(1)

    def store_unselect_all():
        for v in store_vars.values():
            v.set(0)

    store_hdr = tk.Frame(root)
    store_hdr.grid(row=2, column=0, sticky="ew", pady=(10,5))
    store_hdr.grid_columnconfigure((0,1,2), weight=1)
    tk.Button(store_hdr, text="Select All",   command=store_select_all)\
      .grid(row=0, column=0, sticky="e")
    tk.Label(store_hdr, text="Stores", font=("Arial",16))\
      .grid(row=0, column=1)
    tk.Button(store_hdr, text="Unselect All", command=store_unselect_all)\
      .grid(row=0, column=2, sticky="w")

    # --- STORES list ---
    STORE_COLS = 10
    store_frame = ScrollableFrame(root, height=120)
    store_frame.grid(row=3, column=0, sticky="ew", padx=12)
    for c in range(STORE_COLS):
        store_frame.inner.grid_columnconfigure(c, weight=1)

    rows = [
        sorted(all_stores, key=int)[i:i+STORE_COLS]
        for i in range(0, len(all_stores), STORE_COLS)
    ]
    for r, row_items in enumerate(rows):
        offset = (STORE_COLS - len(row_items)) // 2
        for c, sid in enumerate(row_items):
            var = store_vars[sid]
            cb = tk.Checkbutton(store_frame.inner, text=sid, variable=var)
            cb.grid(row=r, column=c + offset, padx=6, pady=3, sticky="n")

    # --- DATE range ---
    date_frame = tk.Frame(root)
    date_frame.grid(row=4, column=0, pady=10)
    tk.Label(date_frame, text="Start Date:").grid(row=0, column=0, padx=5)
    start_entry = tk.Entry(date_frame); start_entry.grid(row=0, column=1, padx=5)
    tk.Label(date_frame, text="End Date:").grid(row=0, column=2, padx=5)
    end_entry   = tk.Entry(date_frame); end_entry.grid(row=0, column=3, padx=5)
    today = datetime.now().date()
    start_entry.insert(0, str(today))
    end_entry.insert(0,   str(today))

    # --- Date presets ---
    range_var = tk.StringVar(value="Today")
    start_entry.bind("<KeyRelease>", lambda e: range_var.set("Custom"))
    end_entry  .bind("<KeyRelease>", lambda e: range_var.set("Custom"))
    opts = ["Custom","Today","Yesterday","Past 2 Days","Past 3 Days",
            "Past 7 Days","Past 14 Days","Past 30 Days"]
    opts_frame = tk.Frame(root)
    opts_frame.grid(row=5, column=0, pady=(0,10))
    for idx, val in enumerate(opts):
        tk.Radiobutton(opts_frame, text=val, variable=range_var, value=val,
                       command=lambda v=val: update_dates(v, start_entry, end_entry)
        ).grid(row=idx//4, column=idx%4, padx=6, pady=4)

    # --- ENDPOINT + VIEW ---
    ep_frame = tk.Frame(root)
    ep_frame.grid(row=6, column=0, pady=(0,12))
    tk.Label(ep_frame, text="Endpoint:", font=("Arial",12))\
      .pack(side="left", padx=5)
    endpoint_var = tk.StringVar(value=list(ENDPOINTS.keys())[0])
    tk.OptionMenu(ep_frame, endpoint_var, *ENDPOINTS.keys())\
      .pack(side="left", padx=5)
    tk.Button(ep_frame, text="View",
              command=lambda: open_view_window(
                  endpoint_var.get(),
                  [s for s,v in store_vars.items() if v.get()],
                  start_entry.get(), end_entry.get()
              )
    ).pack(side="left", padx=10)

    load_external_modules(root)
    root.mainloop()

# ── entry-point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    build_gui()
