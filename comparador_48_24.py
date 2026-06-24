"""
comparador_48_24.py — Pestaña "Plan 48h vs 24h" · Lo Espejo
============================================================
Compara las dos versiones de planificación de cada fecha de entrega,
leyendo en vivo los escenarios guardados en Drivin:

  · Versión 48h = escenario creado 2+ días antes de la fecha de entrega
  · Versión 24h = escenario creado 1 día antes de la fecha de entrega

Foco: cantidad de SALAS y de BULTOS en cada versión + ranking de
salas que reinciden (salen del plan entre 48h y 24h).

No requiere SQLite ni subir archivos: Drivin conserva el histórico.

Integración en app.py:
  · Sidebar:  ...,"⚖️ Plan 48h vs 24h"]
  · Bloque:   elif page=="⚖️ Plan 48h vs 24h":
                  import comparador_48_24
                  comparador_48_24.render()
"""
from __future__ import annotations

import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# ── Marca / constantes (igual que app.py) ───────────────────
TZ_CHILE = ZoneInfo("America/Santiago")
BIMBO_BLUE = "#003087"
BIMBO_CELESTE = "#38bdf8"
BIMBO_GREEN = "#16a34a"
BIMBO_RED = "#dc2626"

BASE = "https://external.driv.in/api/external"
SCHEMA_OBJETIVO = "CV LO ESPEJO"   # esquema a comparar
EXCLUIR_DESC = ("CM",)             # descripciones de prueba a ignorar


# ── API key (mismo patrón que app.py) ───────────────────────
def _api_key() -> str:
    key = os.environ.get("DRIVIN_API_KEY", "")
    if not key:
        try:
            key = st.secrets["DRIVIN_API_KEY"]
        except Exception:
            key = ""
    return key


# ── Acceso a API (cacheado: escenarios históricos no cambian) ─
@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_escenarios(fecha: str) -> list:
    key = _api_key()
    if not key:
        return []
    r = requests.get(f"{BASE}/v2/scenarios", params={"date": fecha},
                     headers={"X-API-KEY": key, "Content-Type": "application/json"},
                     timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("response", []) if data.get("status") == "OK" else []


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_ordenes(token: str) -> list:
    key = _api_key()
    if not key:
        return []
    r = requests.get(f"{BASE}/v2/orders",
                     params={"token": token, "autoassign": 1},
                     headers={"X-API-KEY": key, "Content-Type": "application/json"},
                     timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("response", []) if data.get("status") == "OK" else []


# ── Lógica ──────────────────────────────────────────────────
def _clasificar(escenarios: list, fecha_entrega: date):
    """Devuelve (escenario_48h, escenario_24h) para una fecha de despacho.

    Regla: de todos los escenarios CV LO ESPEJO de esa fecha (excluyendo los
    de prueba 'CM'), el PRIMERO creado es la versión 48h (programación del
    lunes) y el ÚLTIMO creado es la versión 24h (extracción del martes).
    No importa el estado (Aprobado/Optimizado/Iniciado) ni la anticipación
    exacta en días: solo el orden de creación. Si hay 3+, se comparan los
    extremos (primero vs último).
    """
    candidatos = []
    for e in escenarios:
        if e.get("schema_name") != SCHEMA_OBJETIVO:
            continue
        desc = (e.get("description") or "").upper()
        if any(desc.startswith(x) for x in EXCLUIR_DESC):
            continue
        try:
            creado = datetime.fromisoformat(e["created_at"])
        except (KeyError, ValueError):
            continue
        candidatos.append((creado, e))

    if len(candidatos) < 2:
        # Solo hay una versión (o ninguna): no es comparable.
        e_unico = candidatos[0][1] if candidatos else None
        return (e_unico, None) if e_unico else (None, None)

    candidatos.sort(key=lambda x: x[0])      # ascendente por fecha de creación
    e48 = candidatos[0][1]                    # el más antiguo = 48h
    e24 = candidatos[-1][1]                   # el más reciente = 24h
    return e48, e24


def _resumir(registros: list) -> dict:
    """registros de /orders -> {sala: {bultos, nombre, comuna, ruta}}"""
    salas = {}
    for rec in registros:
        code = str(rec.get("code"))
        ordenes = rec.get("orders") or []
        bultos = sum((o.get("units_1") or 0) for o in ordenes)
        nombre = ordenes[0].get("name") if ordenes else ""
        skills = rec.get("skills") or []
        ruta = skills[0] if skills else ""
        salas[code] = {"bultos": bultos, "nombre": nombre or "",
                       "comuna": rec.get("area_level_3") or "",
                       "ruta": ruta}
    return salas


def _comparar_fecha(fecha_entrega: date) -> dict | None:
    fstr = fecha_entrega.strftime("%Y-%m-%d")
    escenarios = _fetch_escenarios(fstr)
    if not escenarios:
        return None
    e48, e24 = _clasificar(escenarios, fecha_entrega)
    if not e48 or not e24:
        return {"fecha": fecha_entrega, "incompleto": True,
                "tiene_48": bool(e48), "tiene_24": bool(e24)}

    s48 = _resumir(_fetch_ordenes(e48["token"]))
    s24 = _resumir(_fetch_ordenes(e24["token"]))
    if not s48 and not s24:
        return None

    set48, set24 = set(s48), set(s24)
    b48 = sum(v["bultos"] for v in s48.values())
    b24 = sum(v["bultos"] for v in s24.values())

    salieron = [{"sala": c, **s48[c]} for c in sorted(set48 - set24)]
    entraron = [{"sala": c, **s24[c]} for c in sorted(set24 - set48)]
    cambios = []
    for c in sorted(set48 & set24):
        a, b = s48[c]["bultos"], s24[c]["bultos"]
        if a != b:
            cambios.append({"sala": c, "nombre": s24[c]["nombre"],
                            "ruta": s24[c].get("ruta", ""),
                            "b48": a, "b24": b, "dif": b - a})

    return {"fecha": fecha_entrega, "incompleto": False,
            "salas48": len(set48), "salas24": len(set24),
            "bultos48": b48, "bultos24": b24,
            "salieron": salieron, "entraron": entraron, "cambios": cambios,
            "creado48": e48.get("created_at"), "creado24": e24.get("created_at")}


def _hora(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).astimezone(TZ_CHILE).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


# ── UI ──────────────────────────────────────────────────────
def render():
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">⚖️ Plan 48h vs 24h — Lo Espejo</h2>',
                unsafe_allow_html=True)
    st.caption("Diferencias de salas validadas y bultos entre la programación (48h) "
               "y la extracción del día previo (24h). Fuente: escenarios Drivin · "
               "esquema CV LO ESPEJO.")

    if not _api_key():
        st.warning("⚠️ Sin API Key. Verifica Settings → Secrets (DRIVIN_API_KEY).")
        return

    hoy = datetime.now(TZ_CHILE).date()
    c1, c2, c3 = st.columns([2, 2, 1])
    desde = c1.date_input("📅 Desde (fecha de entrega)",
                          value=hoy - timedelta(days=6), key="cmp_desde")
    hasta = c2.date_input("📅 Hasta (fecha de entrega)",
                          value=hoy + timedelta(days=2), key="cmp_hasta")
    c3.markdown("<br>", unsafe_allow_html=True)
    comparar = c3.button("🔍 Comparar", type="primary", use_container_width=True)

    if desde > hasta:
        st.warning("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return
    n_dias = (hasta - desde).days + 1
    if n_dias > 60:
        st.warning("Máximo 60 días por consulta.")
        return

    if not comparar:
        st.info("Elige el rango de fechas de **entrega** y presiona Comparar. "
                "Para cada fecha se busca el escenario creado 2 días antes (48h) "
                "y el del día previo (24h).")
        return

    resultados, incompletos = [], []
    barra = st.progress(0.0, text="Consultando escenarios en Drivin…")
    for i in range(n_dias):
        f = desde + timedelta(days=i)
        barra.progress((i + 1) / n_dias, text=f"Procesando {f.strftime('%d/%m/%Y')}…")
        try:
            res = _comparar_fecha(f)
        except requests.RequestException as exc:
            st.error(f"Error de API en {f}: {exc}")
            continue
        if res is None:
            continue
        if res.get("incompleto"):
            incompletos.append(res)
        else:
            resultados.append(res)
    barra.empty()

    if not resultados:
        st.warning("No se encontraron fechas con ambas versiones (48h y 24h) "
                   "en el rango seleccionado.")
        _mostrar_incompletos(incompletos)
        return

    # ── KPIs del período ─────────────────────────────────────
    tb48 = sum(r["bultos48"] for r in resultados)
    tb24 = sum(r["bultos24"] for r in resultados)
    n_sal = sum(len(r["salieron"]) for r in resultados)
    n_ent = sum(len(r["entraron"]) for r in resultados)
    bcaidos = sum(s["bultos"] for r in resultados for s in r["salieron"])
    dif_b = tb24 - tb48
    dif_pct = round(dif_b / tb48 * 100, 1) if tb48 else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📦 Bultos 48h", f"{tb48:,.0f}".replace(",", "."))
    k2.metric("📦 Bultos 24h", f"{tb24:,.0f}".replace(",", "."),
              f"{dif_b:+,.0f} ({dif_pct:+.1f}%)".replace(",", "."))
    k3.metric("🔻 Salas que salieron", n_sal)
    k4.metric("🔺 Salas que entraron", n_ent)

    # ── Tabla diaria ─────────────────────────────────────────
    st.markdown('<div class="section-title">📋 Comparación diaria</div>',
                unsafe_allow_html=True)
    filas = []
    for r in resultados:
        ds = r["salas24"] - r["salas48"]
        db = r["bultos24"] - r["bultos48"]
        filas.append({
            "Fecha entrega": r["fecha"].strftime("%d/%m/%Y"),
            "Salas 48h": r["salas48"], "Salas 24h": r["salas24"],
            "Δ Salas": f"{ds:+d}",
            "Bultos 48h": f"{r['bultos48']:,.0f}".replace(",", "."),
            "Bultos 24h": f"{r['bultos24']:,.0f}".replace(",", "."),
            "Δ Bultos": f"{db:+,.0f}".replace(",", "."),
            "Δ% Bultos": f"{(db / r['bultos48'] * 100) if r['bultos48'] else 0:+.1f}%",
        })
    df_tabla = pd.DataFrame(filas)

    def _color_delta(v):
        try:
            n = float(str(v).replace("%", "").replace(".", "").replace("+", ""))
            if str(v).startswith("-"):
                return "background-color:#fee2e2;color:#991b1b"
            if n > 0:
                return "background-color:#dcfce7;color:#166534"
        except ValueError:
            pass
        return ""

    st.dataframe(
        df_tabla.style.map(_color_delta, subset=["Δ Salas", "Δ Bultos", "Δ% Bultos"]),
        use_container_width=True, hide_index=True)

    # ── Gráfico de desviación ────────────────────────────────
    if len(resultados) > 1:
        gd = pd.DataFrame([{
            "Fecha": r["fecha"].strftime("%d/%m"),
            "Δ Bultos": r["bultos24"] - r["bultos48"],
        } for r in resultados])
        fig = px.bar(gd, x="Fecha", y="Δ Bultos", text="Δ Bultos",
                     color="Δ Bultos",
                     color_continuous_scale=[[0, BIMBO_RED], [0.5, "#e2e8f0"],
                                             [1, BIMBO_GREEN]])
        fig.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(255,255,255,1)",
                          font=dict(color="#1a1a2e", size=12), height=320,
                          margin=dict(l=10, r=10, t=30, b=10), showlegend=False,
                          title=dict(text="Desviación de bultos por fecha (24h − 48h)",
                                     font=dict(color=BIMBO_BLUE, size=14)))
        fig.update_coloraxes(showscale=False)
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

    # ── Salas con movimiento (consolidado, siempre visible) ──
    st.markdown('<div class="section-title">🔄 Salas con movimiento</div>',
                unsafe_allow_html=True)
    movimientos = []
    for r in resultados:
        fstr = r["fecha"].strftime("%d/%m/%Y")
        for s in r["salieron"]:
            movimientos.append({
                "Fecha": fstr, "Tipo": "🔻 Salió", "Sala": s["sala"],
                "Nombre": s["nombre"], "Ruta": s.get("ruta", ""),
                "Comuna": s["comuna"], "Bultos 48h": int(s["bultos"]),
                "Bultos 24h": 0, "Δ Bultos": -int(s["bultos"])})
        for s in r["entraron"]:
            movimientos.append({
                "Fecha": fstr, "Tipo": "🔺 Entró", "Sala": s["sala"],
                "Nombre": s["nombre"], "Ruta": s.get("ruta", ""),
                "Comuna": s["comuna"], "Bultos 48h": 0,
                "Bultos 24h": int(s["bultos"]), "Δ Bultos": int(s["bultos"])})
        for c in r["cambios"]:
            movimientos.append({
                "Fecha": fstr, "Tipo": "↔️ Cambió", "Sala": c["sala"],
                "Nombre": c["nombre"], "Ruta": c.get("ruta", ""),
                "Comuna": "", "Bultos 48h": int(c["b48"]),
                "Bultos 24h": int(c["b24"]), "Δ Bultos": int(c["dif"])})

    if movimientos:
        df_mov = pd.DataFrame(movimientos)

        def _color_tipo(v):
            if "Salió" in str(v):
                return "background-color:#fee2e2;color:#991b1b;font-weight:600"
            if "Entró" in str(v):
                return "background-color:#dcfce7;color:#166534;font-weight:600"
            if "Cambió" in str(v):
                return "background-color:#fef9c3;color:#854d0e;font-weight:600"
            return ""

        def _color_delta(v):
            try:
                n = int(v)
                if n < 0:
                    return "background-color:#fee2e2;color:#991b1b"
                if n > 0:
                    return "background-color:#dcfce7;color:#166534"
            except (ValueError, TypeError):
                pass
            return ""

        st.dataframe(
            df_mov.style
                .map(_color_tipo, subset=["Tipo"])
                .map(_color_delta, subset=["Δ Bultos"]),
            use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(df_mov)} movimiento(s) en el rango · "
                   "🔻 salió del plan · 🔺 entró · ↔️ misma sala, distinto bulto. "
                   "Ruta en blanco = sala sin ruta asignada en ese plan.")
    else:
        st.success("✅ Sin movimientos en el rango: las mismas salas con los mismos "
                   "bultos en 48h y 24h.")

    # ── Ranking de salas reincidentes ────────────────────────
    st.markdown('<div class="section-title">🔻 Ranking de salas que salen del plan</div>',
                unsafe_allow_html=True)
    rein = {}
    for r in resultados:
        for s in r["salieron"]:
            d = rein.setdefault(s["sala"], {"sala": s["sala"], "nombre": s["nombre"],
                                            "ruta": s.get("ruta", ""),
                                            "comuna": s["comuna"], "veces": 0,
                                            "bultos": 0, "fechas": []})
            d["veces"] += 1
            d["bultos"] += s["bultos"]
            d["fechas"].append(r["fecha"].strftime("%d/%m"))
    if rein:
        rk = sorted(rein.values(), key=lambda x: (-x["veces"], -x["bultos"]))
        df_rk = pd.DataFrame([{
            "Sala": d["sala"], "Nombre": d["nombre"], "Ruta": d["ruta"],
            "Comuna": d["comuna"], "Veces caída": d["veces"],
            "Bultos acum.": f"{d['bultos']:,.0f}".replace(",", "."),
            "Fechas": ", ".join(d["fechas"]),
        } for d in rk])

        def _color_veces(v):
            try:
                if int(v) > 1:
                    return "background-color:#fee2e2;color:#991b1b;font-weight:700"
            except (ValueError, TypeError):
                pass
            return ""

        st.dataframe(
            df_rk.style.map(_color_veces, subset=["Veces caída"]),
            use_container_width=True, hide_index=True)
        st.caption("💡 Salas con 2+ caídas (en rojo) son las reincidentes: candidatas "
                   "a revisar con el CEVE o a ajustar en la programación de 48h.")
    else:
        st.success("✅ En el rango seleccionado, ninguna sala salió del plan entre "
                   "48h y 24h.")

    # ── Detalle por fecha ────────────────────────────────────
    st.markdown('<div class="section-title">🔎 Detalle por fecha</div>',
                unsafe_allow_html=True)
    for r in resultados:
        n_mov = len(r["salieron"]) + len(r["entraron"]) + len(r["cambios"])
        etiqueta = (f"{r['fecha'].strftime('%a %d/%m/%Y')} · "
                    f"{r['salas48']}→{r['salas24']} salas · "
                    f"{r['bultos48']:,.0f}→{r['bultos24']:,.0f} bultos · "
                    f"{n_mov} movimiento(s)").replace(",", ".")
        with st.expander(etiqueta, expanded=(n_mov > 0)):
            cc1, cc2 = st.columns(2)
            cc1.caption(f"🕐 48h creada: {_hora(r['creado48'])}")
            cc2.caption(f"🕐 24h creada: {_hora(r['creado24'])}")
            if r["salieron"]:
                st.markdown(f"**🔻 Salieron del plan ({len(r['salieron'])})**")
                dd = pd.DataFrame(r["salieron"])[["sala", "nombre", "ruta", "comuna", "bultos"]].copy()
                dd["bultos"] = dd["bultos"].astype(int)
                dd.columns = ["Sala", "Nombre", "Ruta", "Comuna", "Bultos"]
                st.dataframe(dd, use_container_width=True, hide_index=True)
            if r["entraron"]:
                st.markdown(f"**🔺 Entraron al plan ({len(r['entraron'])})**")
                dd = pd.DataFrame(r["entraron"])[["sala", "nombre", "ruta", "comuna", "bultos"]].copy()
                dd["bultos"] = dd["bultos"].astype(int)
                dd.columns = ["Sala", "Nombre", "Ruta", "Comuna", "Bultos"]
                st.dataframe(dd, use_container_width=True, hide_index=True)
            if r["cambios"]:
                st.markdown(f"**↔️ Cambio de bultos, misma sala ({len(r['cambios'])})**")
                dd = pd.DataFrame(r["cambios"])[["sala", "nombre", "ruta", "b48", "b24", "dif"]].copy()
                dd.columns = ["Sala", "Nombre", "Ruta", "Bultos 48h", "Bultos 24h", "Δ"]
                st.dataframe(dd, use_container_width=True, hide_index=True)
            if n_mov == 0:
                st.success("Sin diferencias: mismas salas y mismos bultos.")

    _mostrar_incompletos(incompletos)


def _mostrar_incompletos(incompletos: list):
    if not incompletos:
        return
    st.divider()
    st.caption("Fechas con una sola versión disponible (no comparables):")
    for r in incompletos:
        tiene = "48h" if r["tiene_48"] else "24h"
        st.caption(f"· {r['fecha'].strftime('%d/%m/%Y')} — solo versión {tiene}")
