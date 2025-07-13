import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Module: daily_sales.py
# Purpose: Display *today's* sales total for every store that is checked in
#          the host application's main window, inside a single popup.
# ---------------------------------------------------------------------------

ENDPOINT_NAME = "Sales Summary"  # key in the host ENDPOINTS dict


def run(window):
    """Populate GUI elements inside the *window* passed by the host."""

    # The host passes us a fresh `Toplevel` window; we just fill it.
    window.title("Daily Sales – Today")
    window.geometry("500x600")

    # ---- layout -----------------------------------------------------------
    text = ScrolledText(window, wrap="word", font=("Consolas", 11))
    text.pack(expand=True, fill="both", padx=12, pady=12)

    def log(line: str = ""):
        text.insert("end", line + "\n")
        text.see("end")

    # ---- pull host globals -----------------------------------------------
    try:
        from __main__ import fetch_data, store_vars, config_accounts  # type: ignore
    except ImportError:
        log("❌ Could not locate required symbols (fetch_data / store_vars / config_accounts).")
        return

    selected = [sid for sid, var in store_vars.items() if var.get()]
    if not selected:
        log("No stores selected in the main window.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    log(f"Date: {today}")
    log(f"Stores: {', '.join(selected)}")
    log("Fetching Sales Summary …\n")

    # ---- parallel API calls ----------------------------------------------
    futures = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for acct in config_accounts:
            cid, ckey = acct["ClientID"], acct["ClientKEY"]
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
                    futures[fut] = store_id

    # ---- collect & show ---------------------------------------------------
    sales_map = {}  # {store : netSales}

    for fut in as_completed(futures):
        store_id = futures[fut]
        result = fut.result()
        if "error" in result:
            sales_map[store_id] = f"ERROR: {result['error']}"
            continue

        data = result.get("data", result)
        # Expecting a list with one element for the day; fallback to dict
        if isinstance(data, list) and data:
            summary = data[0]
        elif isinstance(data, dict):
            summary = data
        else:
            summary = {}

        # Common keys observed: netSales, netSale, netSalesTotal
        for key in ("netSales", "netSale", "netSalesTotal", "netSalesAmount"):
            if key in summary:
                sales_map[store_id] = summary[key]
                break
        else:
            sales_map[store_id] = "N/A"

    # Pretty‑print sorted by store number
    log("=== Daily Net Sales ===")
    for sid in sorted(sales_map, key=int):
        val = sales_map[sid]
        if isinstance(val, (int, float)):
            val = f"${val:,.2f}"
        log(f"Store {sid:>6} : {val}")
