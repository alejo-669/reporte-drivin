# =============================================================
# motor.py — Armado de pallets (copia del motor del proyecto Carga T2)
#
#   - Sala con >= UMBRAL_PALLET_PROPIO de pallet: pallets propios
#   - Salas chicas: pallets compartidos, apilados por secuencia
#     (el próximo en entregar queda arriba)
#   - Bandejas abajo, cajas arriba
# =============================================================
import math

import pandas as pd

from . import ajustes as config

EPS = 1e-9


# -------------------------------------------------------------
# 3. Armado de pallets (propios y compartidos)
# -------------------------------------------------------------
def _nivel_apilado(familias: pd.Series) -> pd.Series:
    """Posición de cada familia en el apilado (0 = base)."""
    return familias.map({f: i for i, f in enumerate(config.ORDEN_APILADO)}).fillna(99)


def _capacidad(lineas_pallet: pd.DataFrame) -> float:
    """1,0 si hay una sola familia; FACTOR_MEZCLA si se mezclan cajas y bandejas."""
    return config.FACTOR_MEZCLA if lineas_pallet["familia"].nunique() > 1 else 1.0


def _llenar(lineas_ordenadas: pd.DataFrame, capacidad: float, prefijo: str, tipo: str) -> list[dict]:
    """Recorre las líneas en orden y las va cargando en pallets de 'capacidad'.

    El orden de las líneas es el orden de carga: lo primero queda abajo.
    """
    filas, n_pallet, ocupado = [], 1, 0.0
    for _, linea in lineas_ordenadas.iterrows():
        pendientes = int(linea["envases"])
        frac_envase = 1 / linea["cupo_pallet"]
        while pendientes > 0:
            caben = math.floor((capacidad - ocupado) / frac_envase + EPS)
            if caben <= 0:  # Pallet lleno -> se abre uno nuevo
                n_pallet, ocupado = n_pallet + 1, 0.0
                continue
            cargar = min(caben, pendientes)
            filas.append({
                "ruta": linea["ruta"], "pallet_id": f"{prefijo}-{n_pallet}",
                "pallet": n_pallet, "tipo_pallet": tipo,
                "cliente": linea["cliente"], "orden_visita": linea["orden_visita"],
                "codigo": linea["codigo"], "n_codigos": linea["n_codigos"],
                "descripcion": linea["descripcion"], "familia": linea["familia"],
                "tipo_envase": linea["tipo_envase"], "envases": cargar,
                "fraccion_pallet": cargar * frac_envase,
                "alto_ocupado_m": cargar / linea["cupo_pallet"] * linea["alto_pallet_full_m"],
            })
            ocupado += cargar * frac_envase
            pendientes -= cargar
    return filas


def armar_pallets(lineas: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reparte la carga de cada ruta en pallets.

    - Cliente con >= UMBRAL_PALLET_PROPIO de pallet: pallets propios.
    - Clientes más chicos: pallets compartidos, cargados del último al primero
      en entregar (el próximo en entregar queda arriba).

    Devuelve:
      detalle : una fila por tramo (cliente + envase) dentro de cada pallet
      pallets : una fila por pallet con ocupación y composición
    """
    filas = []
    lineas = lineas.assign(nivel=_nivel_apilado(lineas["familia"]))

    for ruta, lr in lineas.groupby("ruta", sort=False):
        carga_cliente = lr.groupby("cliente")["fraccion_pallet"].sum()
        grandes = carga_cliente[carga_cliente >= config.UMBRAL_PALLET_PROPIO].index

        # Pallets propios: bandejas abajo, cajas arriba
        for cliente in grandes:
            lc = lr[lr["cliente"] == cliente].sort_values(
                ["nivel", "fraccion_pallet"], ascending=[True, False])
            filas += _llenar(lc, _capacidad(lc), prefijo=str(cliente), tipo="PROPIO")

        # Pallets compartidos: primero el último en entregar (queda abajo)
        chicos = lr[~lr["cliente"].isin(grandes)]
        if not chicos.empty:
            chicos = chicos.sort_values(["orden_visita", "nivel"], ascending=[False, True])
            filas += _llenar(chicos, _capacidad(chicos), prefijo="COMP", tipo="COMPARTIDO")

    detalle = pd.DataFrame(filas)

    # Resumen por pallet
    pallets = (detalle
               .groupby(["ruta", "pallet_id", "pallet", "tipo_pallet"], as_index=False, sort=False)
               .agg(cliente=("cliente", "first"),
                    n_clientes=("cliente", "nunique"),
                    orden_visita=("orden_visita", "min"),  # Debe quedar accesible para su 1ª entrega
                    fraccion=("fraccion_pallet", "sum"),
                    envases=("envases", "sum"),
                    codigos=("n_codigos", "sum"),
                    familias=("familia", lambda f: "+".join(sorted(f.unique()))),
                    alto_m=("alto_ocupado_m", "sum")))
    compartido = pallets["tipo_pallet"] == "COMPARTIDO"
    pallets.loc[compartido, "cliente"] = ("Compartido (" + pallets.loc[compartido, "n_clientes"]
                                          .astype(str) + " clientes)")
    pallets["alto_m"] = pallets["alto_m"].clip(upper=max(config.ALTO_MAX_POR_FAMILIA_M.values()))
    pallets["ocupacion_pct"] = (pallets["fraccion"] * 100).round(1)
    return detalle, pallets


# -------------------------------------------------------------
# 4. Resumen por ruta
# -------------------------------------------------------------
def resumir_rutas(pallets: pd.DataFrame, detalle: pd.DataFrame,
                  posiciones: dict | None = None) -> pd.DataFrame:
    """Pallets usados por ruta contra las posiciones del camión."""
    posiciones = posiciones or {}
    resumen = (pallets.groupby("ruta", as_index=False, sort=False)
               .agg(pallets=("pallet_id", "size"),
                    compartidos=("tipo_pallet", lambda t: (t == "COMPARTIDO").sum()),
                    pallets_equivalentes=("fraccion", "sum"),
                    ocupacion_media_pct=("ocupacion_pct", "mean")))
    resumen.insert(1, "clientes", resumen["ruta"].map(detalle.groupby("ruta")["cliente"].nunique()))
    resumen["posiciones"] = resumen["ruta"].map(posiciones).fillna(
        config.POSICIONES_PALLET_DEFAULT).astype(int)
    resumen["uso_camion_pct"] = (resumen["pallets"] / resumen["posiciones"] * 100).round(1)
    resumen["sobre_cupo"] = resumen["pallets"] > resumen["posiciones"]
    resumen["pallets_equivalentes"] = resumen["pallets_equivalentes"].round(2)
    resumen["ocupacion_media_pct"] = resumen["ocupacion_media_pct"].round(1)
    return resumen
