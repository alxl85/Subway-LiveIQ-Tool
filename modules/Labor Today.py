import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Module: daily_clockins.py
# Purpose: Show *all* employees who have clocked‑in today (whether or not they
#          have clocked out yet) for every store currently checked in the host
#          GUI. Results appear in a single scrollable popup.
# ---------------------------------------------------------------------------

ENDPOINT_NAME = "Daily Timeclock"  # key expected in host ENDPOINTS dict


def run(window):
    """Populate widgets inside the provided *window* (Toplevel)."""

    window.title("Clock‑ins – Today")
    window.geometry("600x650")

    txt = ScrolledText(window, wrap="word", font=("Consolas", 11))
    txt.pack(expand=True, fill="both", padx=12, pady=12)

    def log(line: str = ""):
        txt.insert("end", line + "\n")
        txt.see("end")

    # ---- pull globals from host ------------------------------------------
    try:
        from __main__ import fetch_data, store_vars, config_accounts  # type: ignore
    except ImportError:
        log("❌ Required symbols (fetch_data / store_vars / config_accounts) missing.")
        return

    selected = [sid for sid, var in store_vars.items() if var.get()]
    if not selected:
        log("No stores selected in the main window.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    log(f"Date: {today}")
    log(f"Stores: {', '.join(selected)}")
    log("Fetching Daily Timeclock …\n")

    # ---- concurrent API calls -------------------------------------------
    futures = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for acct in config_accounts:
            cid, ckey, acct_name = acct["ClientID"], acct["ClientKEY"], acct["Name"]
            for store_id in acct.get("StoreIDs", []):
                if store_id in selected:
                    fut = ex.submit(
                        fetch_data,
                        ENDPOINT_NAME,
                        store_id,
                        today,
                        today,
                        cid,
                        ckey,
                    )
                    futures[fut] = (acct_name, store_id)

    # ---- collate results -------------------------------------------------
    for fut in as_completed(futures):
        acct_name, store_id = futures[fut]
        result = fut.result()
        if "error" in result:
            log(f"Store {store_id}  (Acct: {acct_name})  →  ERROR: {result['error']}")
            continue

        data = result.get("data", result)
        if isinstance(data, dict):
            data = [data]

        unique = {}
        for rec in data or []:
            name = rec.get("employeeName", "<unknown>")
            clock_in = rec.get("clockInDateTime") or rec.get("clockIn")
            job = rec.get("jobDescription") or rec.get("jobCode", "")
            # keep earliest clock‑in per employee
            if name not in unique or (clock_in and clock_in < unique[name]["clock_in"]):
                unique[name] = {"clock_in": clock_in, "job": job}

        log(f"➤ Store {store_id}  (Acct: {acct_name})")
        if not unique:
            log("   — No clock‑ins recorded today —\n")
            continue
        for emp, meta in sorted(unique.items(), key=lambda x: x[0].lower()):
            log(f"   • {emp}  |  In: {meta['clock_in']}  |  {meta['job']}")
        log()
