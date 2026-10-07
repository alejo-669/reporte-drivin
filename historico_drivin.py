"""
historico_drivin.py — Lee el respaldo diario de /pods guardado en GitHub
========================================================================
La API de Drivin solo entrega ~7 días. Los días más antiguos se leen del
repo PRIVADO de respaldo (lo llena GitHub Actions cada noche con un
archivo por día: pods/AAAA-MM-DD.json.gz).

Secrets necesarios en Streamlit Cloud (Settings → Secrets):
    HISTORICO_REPO  = "alejo-669/drivin-historico"
    HISTORICO_TOKEN = "github_pat_..."   # token de solo lectura a ese repo

Si no están configurados, el dashboard funciona igual que antes (solo 7 días).
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import date, timedelta

import requests
import streamlit as st

API_GITHUB = "https://api.github.com/repos/{repo}/contents/pods/{fecha}.json.gz"


def _secreto(nombre: str) -> str:
    """Lee un secret de Streamlit o, en local, de una variable de entorno."""
    try:
        valor = st.secrets[nombre]
    except Exception:
        valor = os.environ.get(nombre, "")
    return str(valor or "").strip()


def configurado() -> bool:
    return bool(_secreto("HISTORICO_REPO") and _secreto("HISTORICO_TOKEN"))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _bajar_dia(fecha: str) -> list | None:
    """Paradas de un día desde el respaldo. None = ese día no está respaldado."""
    url = API_GITHUB.format(repo=_secreto("HISTORICO_REPO"), fecha=fecha)
    r = requests.get(url, timeout=60, headers={
        "Authorization": f"Bearer {_secreto('HISTORICO_TOKEN')}",
        "Accept": "application/vnd.github.raw+json",   # contenido crudo (hasta 100 MB)
        "X-GitHub-Api-Version": "2022-11-28",
    })
    if r.status_code == 404:
        return None
    r.raise_for_status()
    contenido = r.content
    if contenido[:2] == b"\x1f\x8b":          # viene comprimido (lo normal)
        contenido = gzip.decompress(contenido)
    return json.loads(contenido)


def cargar(desde: date, hasta: date) -> tuple[list, list[date]]:
    """Devuelve (registros de /pods, días que no están en el respaldo)."""
    registros, faltantes = [], []
    if not configurado() or desde > hasta:
        return registros, faltantes
    for i in range((hasta - desde).days + 1):
        dia = desde + timedelta(days=i)
        try:
            datos = _bajar_dia(dia.isoformat())
        except requests.RequestException as e:
            st.error(f"Error leyendo el respaldo del {dia:%d/%m}: {e}")
            datos = None
        if datos is None:
            faltantes.append(dia)
        else:
            registros.extend(datos)
    return registros, faltantes
