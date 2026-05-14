"""
fetch_data.py — Consulta la API de Drivin cada 10 minutos y guarda en SQLite.

Uso:
  python fetch_data.py            # Ejecuta una vez (últimos 7 días)
  python fetch_data.py --loop     # Ejecuta cada 10 minutos en loop

En Streamlit Cloud este script se ejecuta desde app.py directamente,
así que no necesitas correrlo por separado.
"""

import os
import json
import sqlite3
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import sys

# ── Configuración ──────────────────────────────────────────
API_KEY = os.environ.get("DRIVIN_API_KEY", "")
BASE_URL = "https://external.driv.in/api/external/v2/pods"
DB_PATH = "drivin_data.db"
FETCH_INTERVAL = 600  # 10 minutos en segundos


def fetch_pods(start_date: str, end_date: str) -> list:
    """Consulta el endpoint de pods de Drivin."""
    headers = {
        "X-API-KEY": API_KEY,
        "Content-Type": "application/json",
    }
    params = {
        "start_date": start_date,
        "end_date": end_date,
    }
    try:
        resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", [])
    except Exception as e:
        print(f"[ERROR] Fallo al consultar API: {e}")
        return []


def flatten_records(records: list) -> pd.DataFrame:
    """Aplana los registros de la API en un DataFrame plano (1 fila por orden)."""
    rows = []
    for r in records:
        base = {
            "planned_date": r.get("planned_date"),
            "description": r.get("description"),
            "vehicle_code": r.get("vehicle_code"),
            "schema_name": r.get("schema_name"),
            "fleet_name": r.get("fleet_name"),
            "organization_name": r.get("organization_name"),
            "route_is_approved": r.get("route_is_approved"),
            "route_is_started": r.get("route_is_started"),
            "route_is_finished": r.get("route_is_finished"),
            "route_approved_at": r.get("route_approved_at"),
            "route_started_at": r.get("route_started_at"),
            "route_finished_at": r.get("route_finished_at"),
            "driver_name": (r.get("driver_name") or "").strip(),
            "driver_email": r.get("driver_email"),
            "employer_name": r.get("employer_name"),
            "address_name": r.get("address_name"),
            "address_code": r.get("address_code"),
            "address_address_1": r.get("address_address_1"),
            "address_city": r.get("address_city"),
            "address_state": r.get("address_state"),
            "address_lat": r.get("address_lat"),
            "address_lng": r.get("address_lng"),
            "planned_service_time": r.get("planned_service_time"),
            "eta": r.get("eta"),
            "trip_number": r.get("trip_number"),
            "time_window_start": (r.get("time_window") or {}).get("start"),
            "time_window_end": (r.get("time_window") or {}).get("end"),
            "tracked_arrival": r.get("tracked_arrival"),
            "tracked_leave": r.get("tracked_leave"),
            "tracked_service_time": r.get("tracked_service_time"),
            "visit_arrival": r.get("visit_arrival"),
            "visit_leave": r.get("visit_leave"),
            "route_code": r.get("route_code"),
        }
        orders = r.get("orders", [])
        if not orders:
            rows.append({**base, "order_code": None, "status": None,
                         "reason": None, "otif": None, "near_pod": None,
                         "units_1": 0, "units_2": 0, "units_3": 0,
                         "client_name": None, "client_code": None,
                         "tags": None, "pod_arrival": None})
        else:
            for o in orders:
                rows.append({
                    **base,
                    "order_code": o.get("code"),
                    "status": o.get("status"),
                    "reason": o.get("reason"),
                    "otif": o.get("otif"),
                    "near_pod": o.get("near_pod"),
                    "units_1": o.get("units_1") or 0,
                    "units_2": o.get("units_2") or 0,
                    "units_3": o.get("units_3") or 0,
                    "client_name": o.get("client_name"),
                    "client_code": o.get("client_code"),
                    "tags": json.dumps(o.get("tags", [])),
                    "pod_arrival": o.get("pod_arrival"),
                })
    return pd.DataFrame(rows)


def save_to_db(df: pd.DataFrame):
    """Guarda en SQLite, deduplicando por order_code + planned_date."""
    if df.empty:
        return
    conn = sqlite3.connect(DB_PATH)
    # Crear tabla si no existe
    df.head(0).to_sql("deliveries", conn, if_exists="append", index=False)

    # Leer códigos existentes para deduplicar
    try:
        existing = pd.read_sql(
            "SELECT DISTINCT order_code, planned_date FROM deliveries", conn
        )
        existing_keys = set(
            zip(existing["order_code"], existing["planned_date"])
        )
        df["_key"] = list(zip(df["order_code"], df["planned_date"]))
        new_rows = df[~df["_key"].isin(existing_keys)].drop(columns=["_key"])
    except Exception:
        new_rows = df

    if not new_rows.empty:
        new_rows.to_sql("deliveries", conn, if_exists="append", index=False)
        print(f"[OK] {len(new_rows)} registros nuevos guardados.")
    else:
        print("[OK] Sin registros nuevos (ya existían).")
    conn.close()


def run_once():
    """Ejecuta una consulta de los últimos 7 días."""
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"[FETCH] Consultando {week_ago} → {today} ...")
    records = fetch_pods(week_ago, today)
    if records:
        df = flatten_records(records)
        save_to_db(df)
        print(f"[OK] {len(records)} registros procesados.")
    else:
        print("[WARN] Sin datos de la API.")


if __name__ == "__main__":
    if not API_KEY:
        print("[ERROR] Define la variable de entorno DRIVIN_API_KEY")
        sys.exit(1)

    if "--loop" in sys.argv:
        print(f"[LOOP] Ejecutando cada {FETCH_INTERVAL // 60} minutos. Ctrl+C para detener.")
        while True:
            run_once()
            time.sleep(FETCH_INTERVAL)
    else:
        run_once()
