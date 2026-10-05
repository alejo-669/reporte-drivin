"""
plan_vs_distribucion.py — Pestaña "⚖️ Plan vs Distribución"
===========================================================
Reemplaza al comparador 48h vs 24h. El equipo programa UNA vez y el botón 3
del bot DRIVIN pone el plan al día con la distribución. Esta pestaña muestra,
por fecha, CV y sala, qué cambió entre lo programado y lo que salió:

  PROGRAMADO  -> custom_2 "v1|u1=..|u2=.."        (al programar)
  SOLICITADO  -> custom_3 "v1|o1=..|o2=..|e=.."   (al distribuir + estado de la sala)
  DISTRIBUIDO -> units_1 / units_2
  QUIEBRE POR PRODUCTO -> custom_4 "v1|producto:unidades:envases:venta:descripcion|..."

  programado -> solicitado  = CAMBIO COMERCIAL (ventas: sube, baja, agrega, elimina)
  solicitado -> distribuido = QUIEBRE (no había producto)

Todo se lee desde los planes de Drivin (incluye salas sin camión: nuevas y eliminadas).

Integración en app.py:
  · Sidebar: reemplaza "⚖️ Plan 48h vs 24h" por "⚖️ Plan vs Distribución"
  · Bloque (antes de "# Load data"):
        if page=="⚖️ Plan vs Distribución":
            import plan_vs_distribucion
            plan_vs_distribucion.render()
            st.stop()
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

TZ_CHILE = ZoneInfo("America/Santiago")
BIMBO_BLUE = "#003087"
AMBAR = "#F0A202"
ROJO = "#dc2626"
VERDE = "#16a34a"
GRIS = "#94a3b8"
BASE = "https://external.driv.in/api/external/v2"
EXCLUIR_DESC = ("CM",)          # planes de prueba
META_FR = 95.0

TIPOS = {
    "NUEVA": "🆕 Sala nueva", "ELIMINADA": "🔻 Eliminada (ventas)",
    "QUIEBRE_TOTAL": "⛔ Quiebre total", "REVALIDADA": "🔁 Revalidada",
    "COMERCIAL": "✏️ Cambio comercial", "QUIEBRE": "📉 Quiebre parcial",
}


# ── 1. Datos ───────────────────────────────────────────────────
def _api_key() -> str:
    key = os.environ.get("DRIVIN_API_KEY", "")
    if not key:
        try:
            key = st.secrets["DRIVIN_API_KEY"]
        except Exception:
            key = ""
    return key


def _get(ruta: str, params: dict) -> list:
    r = requests.get(f"{BASE}{ruta}", params=params, timeout=60,
                     headers={"X-API-KEY": _api_key(), "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json().get("response", []) or []


def _marca(texto) -> dict:
    """'v1|u1=184|u2=3709522' -> {'u1': 184.0, 'u2': 3709522.0}"""
    t = str(texto or "")
    if not t.startswith("v1|"):
        return {}
    datos = {}
    for parte in t.split("|")[1:]:
        if "=" in parte:
            k, v = parte.split("=", 1)
            try:
                datos[k] = float(v)
            except ValueError:
                datos[k] = v
    return datos


@st.cache_data(ttl=600, show_spinner=False)
def cargar_fecha(fecha: str) -> pd.DataFrame:
    """Una fila por sala de los planes de una fecha (último plan de cada CEVE)."""
    planes = [e for e in _get("/scenarios", {"date": fecha})
              if not str(e.get("description") or "").upper().startswith(EXCLUIR_DESC)]
    ultimo = {}
    for e in sorted(planes, key=lambda x: str(x.get("created_at") or "")):
        ultimo[e.get("description")] = e                       # se queda con el más reciente
    filas = []
    for desc, e in ultimo.items():
        for c in _get("/orders", {"token": e["token"], "autoassign": 1}):
            for o in c.get("orders", []) or []:
                prog, sol = _marca(o.get("custom_2")), _marca(o.get("custom_3"))
                filas.append({
                    "fecha": fecha, "centro": e.get("schema_name") or desc, "plan": desc,
                    "sala": str(c.get("code")), "nombre": (o.get("name") or "")[:35],
                    "comuna": c.get("area_level_3") or "",
                    "camion": o.get("vehicle_code") or "",
                    "prog_env": prog.get("u1"), "prog_venta": prog.get("u2"),
                    "sol_env": sol.get("o1"), "sol_venta": sol.get("o2"), "estado": sol.get("e"),
                    "dist_env": float(o.get("units_1") or 0), "dist_venta": float(o.get("units_2") or 0),
                    "quiebre_prod": o.get("custom_4") or "",
                })
    return pd.DataFrame(filas)


def cascada(df: pd.DataFrame, medida: str = "env") -> dict:
    """
    Programado -> +nuevas -> -eliminadas -> ±ajuste valorización -> ±comercial -> -quiebre -> distribuido.

    En VENTA el cambio comercial se mide con los envases (lo que ventas cambió de verdad) a
    precio programado por envase; el resto de la diferencia programado vs solicitado es
    AJUSTE DE VALORIZACIÓN (productos que MC1 tenía en $0 al programar, cambios de precio).
    Así el quiebre en venta = suma del detalle por producto (custom_4).
    """
    p, s, d = f"prog_{medida}", f"sol_{medida}", f"dist_{medida}"
    e = df["estado"]
    sigue = e.isin(["OK", "QUIEBRE_TOTAL", "REVALIDADA"])
    dif = (df.loc[sigue, s] - df.loc[sigue, p])
    if medida == "venta":
        g = df.loc[sigue]
        precio_env = (g["prog_venta"] / g["prog_env"].where(g["prog_env"] > 0)).fillna(0)
        comercial = ((g["sol_env"] - g["prog_env"]) * precio_env)
        ajuste = dif - comercial
    else:
        comercial, ajuste = dif, dif * 0
    return {
        "programado": df.loc[e != "NUEVA", p].sum(),
        "nuevas": df.loc[e == "NUEVA", s].sum(),
        "eliminadas": -df.loc[e == "ELIMINADA", p].sum(),
        "ajuste": ajuste.sum(),
        "comercial": comercial.sum(),
        "quiebre": -(df.loc[e != "ELIMINADA", s] - df.loc[e != "ELIMINADA", d]).sum(),
        "distribuido": df[d].sum(),
    }


def _productos(texto) -> list[dict]:
    """'v1|964770:80:4:207240:MinPing10p200g|...' -> lista de productos con quiebre."""
    t = str(texto or "")
    if not t.startswith("v1|"):
        return []
    filas = []
    for parte in t.split("|")[1:]:
        campos = parte.split(":", 4)
        if len(campos) < 4:
            continue
        try:
            otros = campos[0] == "OTROS"      # el bot agrupa ahí lo que no cabe en el campo de Drivin
            filas.append({"producto": campos[0], "unidades": float(campos[1]), "envases": float(campos[2]),
                          "venta": float(campos[3]),
                          "descripcion": "Otros (no detallados)" if otros else (campos[4] if len(campos) > 4 else "")})
        except ValueError:
            continue
    return filas


def quiebre_productos(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por fecha, CV, sala y producto con lo que no salió."""
    filas = [{"fecha": r.fecha, "centro": r.centro, "sala": r.sala, "nombre": r.nombre, **p}
             for r in df[df["estado"] != "ELIMINADA"].itertuples() for p in _productos(r.quiebre_prod)]
    return pd.DataFrame(filas)


def movimientos(df: pd.DataFrame) -> pd.DataFrame:
    """Salas con algún cambio, con su tipo principal."""
    m = df.copy()
    m["d_comercial"] = (m["sol_env"] - m["prog_env"]).where(m["estado"] != "NUEVA", m["sol_env"])
    m.loc[m["estado"] == "ELIMINADA", "d_comercial"] = -m["prog_env"]
    m["d_quiebre"] = -(m["sol_env"] - m["dist_env"]).where(m["estado"] != "ELIMINADA", 0)
    m["tipo"] = m["estado"].map({k: TIPOS[k] for k in ["NUEVA", "ELIMINADA", "QUIEBRE_TOTAL", "REVALIDADA"]})
    m.loc[m["tipo"].isna() & (m["d_comercial"] != 0), "tipo"] = TIPOS["COMERCIAL"]
    m.loc[m["tipo"].isna() & (m["d_quiebre"] != 0), "tipo"] = TIPOS["QUIEBRE"]
    return m[m["tipo"].notna()]


# ── 2. Pantalla ────────────────────────────────────────────────
def _n(v) -> str:
    """Entero con separador de miles chileno: 1234567 -> '1.234.567'."""
    if v is None or pd.isna(v):
        return ""
    return f"{v:,.0f}".replace(",", ".")


def _pesos(v) -> str:
    if v is None or pd.isna(v):
        return ""
    return ("-" if v < 0 else "") + "$" + _n(abs(v))


def _delta(v) -> str:
    """Variación con signo: +12 / -3 / 0."""
    if v is None or pd.isna(v):
        return ""
    return ("+" if v > 0 else "") + _n(v)


def _formatear(tabla: pd.DataFrame, enteros=(), deltas=(), pesos=(), pct=()):
    """Styler sin los 6 decimales por defecto: enteros, deltas con signo, pesos y %."""
    fmt = {c: _n for c in enteros if c in tabla}
    fmt.update({c: _delta for c in deltas if c in tabla})
    fmt.update({c: _pesos for c in pesos if c in tabla})
    fmt.update({c: (lambda v: "" if pd.isna(v) else f"{v:.1f}%".replace(".", ","))
                for c in pct if c in tabla})
    return tabla.style.format(fmt)


def _chequeo_venta(df: pd.DataFrame) -> list[str]:
    """Detecta datos de venta inconsistentes (versiones antiguas del botón 3)."""
    ce, cv = cascada(df, "env"), cascada(df, "venta")
    avisos = []
    if abs(ce["quiebre"]) > 0 and abs(cv["distribuido"] - cv["programado"]) < 1:
        avisos.append("La **venta distribuida es idéntica a la programada** aunque en envases hay quiebre "
                      f"({_n(ce['quiebre'])} env.): vuelve a correr el botón 3 con la versión actual.")
    detalle = quiebre_productos(df)["venta"].sum() if "quiebre_prod" in df else 0
    if detalle and abs(detalle + cv["quiebre"]) > max(1000, 0.01 * detalle):
        avisos.append(f"El detalle por producto ({_pesos(detalle)}) no cuadra con el quiebre de la cascada "
                      f"({_pesos(-cv['quiebre'])}): vuelve a correr el botón 3 con la versión actual.")
    return avisos


def _grafico_cascada(c: dict, titulo: str, pesos: bool):
    pasos = [("Programado", c["programado"]), ("Salas nuevas", c["nuevas"]),
             ("Salas eliminadas", c["eliminadas"])]
    if pesos:
        pasos.append(("Ajuste valorización", c["ajuste"]))
    pasos += [("Cambio comercial", c["comercial"]), ("Quiebre", c["quiebre"]), ("Distribuido", c["distribuido"])]
    etiquetas, valores = [x for x, _ in pasos], [v for _, v in pasos]
    ultimo = len(valores) - 1
    fmt = _pesos if pesos else _n
    fig = go.Figure(go.Waterfall(
        x=etiquetas, y=valores, measure=["absolute"] + ["relative"] * (ultimo - 1) + ["total"],
        text=[fmt(v) if i in (0, ultimo) else ("+" if v > 0 else "") + fmt(v) for i, v in enumerate(valores)],
        textposition="outside",
        increasing={"marker": {"color": VERDE}}, decreasing={"marker": {"color": ROJO}},
        totals={"marker": {"color": BIMBO_BLUE}}, connector={"line": {"color": GRIS}}))
    fig.update_layout(title=dict(text=titulo, font=dict(color=BIMBO_BLUE, size=15)), template="plotly_white",
                      height=380, margin=dict(l=10, r=10, t=50, b=10), showlegend=False)
    return fig


def _tab_productos(df: pd.DataFrame):
    """Qué productos faltaron, en cuántas salas y cuánta venta no se despachó."""
    qp = quiebre_productos(df)
    if qp.empty:
        st.info("Sin detalle por producto en este rango. El detalle se llena al correr el botón 3 "
                "con la versión que escribe custom_4.")
        return
    total = qp["venta"].sum()
    rk = (qp.groupby("producto", as_index=False)
          .agg(descripcion=("descripcion", "first"), salas=("sala", "nunique"),
               unidades=("unidades", "sum"), envases=("envases", "sum"), venta=("venta", "sum"))
          .sort_values("venta", ascending=False))
    rk["pct"] = rk["venta"] / total * 100 if total else 0
    rk["acum"] = rk["pct"].cumsum()

    # Conclusión primero: cuánto se perdió y cuántos productos lo explican
    n80 = int((rk["acum"] < 80).sum()) + 1
    k = st.columns(4)
    k[0].metric("Venta no despachada", _pesos(total))
    k[1].metric("Productos con quiebre", f"{len(rk)}")
    k[2].metric("Salas afectadas", f"{qp['sala'].nunique()}")
    k[3].metric("Explican el 80%", f"{min(n80, len(rk))} productos")

    top = rk.head(10).iloc[::-1]
    fig = go.Figure(go.Bar(x=top["venta"], y=top["descripcion"].where(top["descripcion"] != "", top["producto"]),
                           orientation="h", marker_color=ROJO,
                           text=[_pesos(v) for v in top["venta"]], textposition="outside"))
    fig.update_layout(title="Top 10 productos por venta no despachada", template="plotly_white",
                      height=120 + 32 * len(top), margin=dict(l=10, r=60, t=50, b=10),
                      xaxis=dict(showticklabels=False))
    st.plotly_chart(fig, width="stretch")

    tabla = rk.rename(columns={"producto": "Producto", "descripcion": "Descripción", "salas": "Salas",
                               "unidades": "Unidades no despachadas", "envases": "Envases no despachados",
                               "venta": "Venta no despachada", "pct": "% del quiebre", "acum": "% acumulado"})
    st.dataframe(_formatear(tabla, enteros=["Salas", "Unidades no despachadas", "Envases no despachados"],
                            pesos=["Venta no despachada"], pct=["% del quiebre", "% acumulado"]),
                 width="stretch", hide_index=True)

    with st.expander("Ver detalle por sala"):
        det = qp.sort_values(["fecha", "centro", "sala", "venta"], ascending=[True, True, True, False])
        det = det[["fecha", "centro", "sala", "nombre", "producto", "descripcion", "unidades", "envases", "venta"]]
        det.columns = ["Fecha", "CV", "Sala", "Nombre", "Producto", "Descripción", "Unidades", "Envases", "Venta"]
        st.dataframe(_formatear(det, enteros=["Unidades", "Envases"], pesos=["Venta"]),
                     width="stretch", hide_index=True)
    st.caption("Venta no despachada = lo que la sala pidió y no salió por falta de producto. "
               "Suma lo mismo que la barra roja de quiebre en la cascada (vista venta). "
               "'Otros' agrupa los productos menores que no caben en el campo de Drivin; "
               "el detalle completo está en el Excel del botón 3.")


def render():
    st.markdown(f'<h2 style="color:{BIMBO_BLUE}">⚖️ Plan vs Distribución</h2>', unsafe_allow_html=True)
    st.caption("Qué cambió entre lo programado y lo que salió, sala por sala. Cambio comercial = ventas "
               "modificó el pedido; quiebre = no había producto. Se llena con el botón 3 del bot DRIVIN.")
    if not _api_key():
        st.warning("⚠️ Sin API Key. Verifica Settings → Secrets (DRIVIN_API_KEY).")
        return

    hoy = datetime.now(TZ_CHILE).date()
    c1, c2, c3 = st.columns([1.3, 1.3, 2])
    desde = c1.date_input("📅 Desde (entrega)", value=hoy - timedelta(days=6), key="pvd_desde")
    hasta = c2.date_input("📅 Hasta (entrega)", value=hoy + timedelta(days=1), key="pvd_hasta")
    if desde > hasta or (hasta - desde).days > 31:
        st.warning("Rango no válido (máximo 31 días).")
        return

    tablas = []
    with st.spinner("Leyendo planes de Drivin..."):
        for i in range((hasta - desde).days + 1):
            try:
                tablas.append(cargar_fecha((desde + timedelta(days=i)).strftime("%Y-%m-%d")))
            except requests.RequestException as e:
                st.error(f"Error de API: {e}")
    todo = pd.concat([t for t in tablas if not t.empty], ignore_index=True) if any(
        not t.empty for t in tablas) else pd.DataFrame()
    if todo.empty:
        st.info("Sin planes en Drivin para esas fechas.")
        return

    centros = ["Todos"] + sorted(todo["centro"].dropna().unique())
    centro = c3.selectbox("🏭 Centro", centros, key="pvd_centro")
    if centro != "Todos":
        todo = todo[todo["centro"] == centro]
    df = todo[todo["estado"].notna() & todo["prog_env"].notna()].copy()
    st.caption(f"Salas con distribución registrada: **{len(df)} de {len(todo)}** "
               "(las demás aún no pasan por el botón 3).")
    if df.empty:
        st.info("Todavía no hay planes actualizados con la distribución en este rango.")
        return

    # ── Acciones pendientes: salas sin camión que deben salir
    pend = df[(df["estado"].isin(["NUEVA", "REVALIDADA"])) & (df["camion"] == "") &
              (pd.to_datetime(df["fecha"]).dt.date >= hoy)]
    if not pend.empty:
        st.markdown(f'<div class="alerta-yellow">⚠️ <b>{len(pend)} salas nuevas sin camión</b> para hoy o '
                    f'después: asignarlas en Drivin → {", ".join(pend["sala"].head(20))}</div>',
                    unsafe_allow_html=True)

    # ── KPIs y cascada
    medida = st.radio("Ver en", ["Envases", "Venta"], horizontal=True, key="pvd_medida")
    m, pesos = ("env", False) if medida == "Envases" else ("venta", True)
    c = cascada(df, m)
    fmt = _pesos if pesos else _n
    if pesos:
        avisos = _chequeo_venta(df)
        if avisos:
            st.warning("⚠️ **La vista en venta no es confiable todavía.** Usa envases mientras se corrige "
                       "el bot.\n\n" + "\n\n".join(f"• {a}" for a in avisos))
    solicitado_total = c["programado"] + c["nuevas"] + c["eliminadas"] + c["ajuste"] + c["comercial"]
    fr = c["distribuido"] / solicitado_total * 100 if solicitado_total else 0
    k = st.columns(6 if pesos else 5)
    i = iter(k)
    next(i).metric("Programado", fmt(c["programado"]))
    if pesos:
        next(i).metric("Ajuste valorización", fmt(c["ajuste"]),
                       help="Diferencia de precio entre lo programado y lo solicitado sin que ventas cambie "
                            "envases: productos que MC1 tenía en $0 al programar o cambios de precio. "
                            "Con la foto del pedido programado (bot v3) debería ser casi cero.")
    next(i).metric("Cambio comercial (ventas)", fmt(c["nuevas"] + c["eliminadas"] + c["comercial"]),
                   help="Salas nuevas + eliminadas + aumentos/bajas de pedido")
    next(i).metric("Quiebre", fmt(c["quiebre"]), help="Lo solicitado que no salió por falta de producto. "
                   "En venta = suma de la pestaña 📦 Productos con quiebre")
    next(i).metric("Distribuido", fmt(c["distribuido"]))
    next(i).metric("Fill rate", f"{fr:.1f}%", f"{fr - META_FR:+.1f} pp vs meta {META_FR:.0f}%")
    st.plotly_chart(_grafico_cascada(c, f"Del plan a la distribución · {medida.lower()}", pesos),
                    width="stretch")

    t1, t5, t2, t3, t4 = st.tabs(["🔄 Salas con movimiento", "📦 Productos con quiebre",
                                  "📋 Por fecha y CV", "🏆 Rankings", "📉 Fill rate"])

    with t5:
        _tab_productos(df)

    with t1:
        mov = movimientos(df)
        if mov.empty:
            st.success("✅ Sin movimientos: todo salió tal como se programó.")
        else:
            tabla = mov[["fecha", "centro", "tipo", "sala", "nombre", "camion", "prog_env", "sol_env",
                         "dist_env", "d_comercial", "d_quiebre"]].rename(columns={
                "fecha": "Fecha", "centro": "CV", "tipo": "Tipo", "sala": "Sala", "nombre": "Nombre",
                "camion": "Camión", "prog_env": "Programado", "sol_env": "Solicitado",
                "dist_env": "Distribuido", "d_comercial": "Δ Comercial", "d_quiebre": "Δ Quiebre"})

            def _color(v):
                v = str(v)
                if "nueva" in v.lower() or "Revalidada" in v:
                    return "background-color:#dcfce7;color:#166534;font-weight:600"
                if "Eliminada" in v or "total" in v:
                    return "background-color:#fee2e2;color:#991b1b;font-weight:600"
                if "comercial" in v:
                    return "background-color:#fef9c3;color:#854d0e;font-weight:600"
                if "Quiebre" in v:
                    return "background-color:#ffedd5;color:#9a3412;font-weight:600"
                return ""
            tabla = tabla.sort_values(["Fecha", "CV", "Tipo"])
            st.dataframe(_formatear(tabla, enteros=["Programado", "Solicitado", "Distribuido"],
                                    deltas=["Δ Comercial", "Δ Quiebre"]).map(_color, subset=["Tipo"]),
                         width="stretch", hide_index=True)
            st.caption("Δ Comercial: cambio del pedido por ventas · Δ Quiebre: lo que no salió por falta de producto.")

    with t2:
        filas = []
        for (f, cv), g in df.groupby(["fecha", "centro"]):
            cc = cascada(g, "env")
            sol = cc["programado"] + cc["nuevas"] + cc["eliminadas"] + cc["ajuste"] + cc["comercial"]
            filas.append({"Fecha": f, "CV": cv, "Programado": cc["programado"], "Nuevas": cc["nuevas"],
                          "Eliminadas": cc["eliminadas"], "Comercial": cc["comercial"],
                          "Quiebre": cc["quiebre"], "Distribuido": cc["distribuido"],
                          "Fill rate %": round(cc["distribuido"] / sol * 100, 1) if sol else None})
        st.dataframe(_formatear(pd.DataFrame(filas), enteros=["Programado", "Distribuido"],
                                deltas=["Nuevas", "Eliminadas", "Comercial", "Quiebre"],
                                pct=["Fill rate %"]),
                     width="stretch", hide_index=True)

    with t3:
        mov = movimientos(df)
        r1, r2 = st.columns(2)
        com = mov[mov["d_comercial"] != 0]
        with r1:
            st.markdown("**✏️ Salas con más cambios de ventas**")
            if com.empty:
                st.caption("Sin cambios comerciales en el rango.")
            else:
                rk = (com.groupby(["sala", "nombre", "centro"], as_index=False)
                      .agg(veces=("fecha", "nunique"), envases=("d_comercial", "sum"),
                           eliminaciones=("estado", lambda e: (e == "ELIMINADA").sum()))
                      .sort_values(["veces", "envases"], ascending=[False, True]).head(20))
                rk = rk.rename(columns={"sala": "Sala", "nombre": "Nombre", "centro": "CV",
                                        "veces": "Días con cambio", "envases": "Δ envases",
                                        "eliminaciones": "Eliminaciones"})
                st.dataframe(_formatear(rk, deltas=["Δ envases"]), width="stretch", hide_index=True)
        qui = mov[mov["d_quiebre"] != 0]
        with r2:
            st.markdown("**📉 Salas con más quiebre**")
            if qui.empty:
                st.caption("Sin quiebre en el rango.")
            else:
                q = qui.assign(venta=qui["sol_venta"] - qui["dist_venta"])
                rk = (q.groupby(["sala", "nombre", "centro"], as_index=False)
                      .agg(veces=("fecha", "nunique"), envases=("d_quiebre", "sum"), venta=("venta", "sum"))
                      .sort_values(["veces", "envases"], ascending=[False, True]).head(20))
                rk["venta"] = rk["venta"].map(_pesos)
                rk = rk.rename(columns={"sala": "Sala", "nombre": "Nombre", "centro": "CV",
                                        "veces": "Días con quiebre", "envases": "Envases no despachados",
                                        "venta": "Venta no despachada"})
                st.dataframe(_formatear(rk, deltas=["Envases no despachados"]),
                             width="stretch", hide_index=True)
        st.caption("💡 Las salas que se repiten son las que hay que conversar con ventas (cambios) "
                   "o con abastecimiento (quiebre).")

    with t4:
        g = df[df["estado"] != "ELIMINADA"].groupby("centro", as_index=False).agg(
            sol=("sol_env", "sum"), dist=("dist_env", "sum"))
        g["fr"] = (g["dist"] / g["sol"] * 100).round(1)
        g = g.sort_values("fr")
        fig = go.Figure(go.Bar(x=g["fr"], y=g["centro"], orientation="h",
                               marker_color=[ROJO if v < META_FR else VERDE for v in g["fr"]],
                               text=[f"{v:.1f}%" for v in g["fr"]], textposition="outside"))
        fig.add_vline(x=META_FR, line_dash="dash", line_color=AMBAR,
                      annotation_text=f"Meta {META_FR:.0f}%", annotation_position="top")
        fig.update_layout(title="Fill rate de envases por CV (solicitado vs distribuido)",
                          template="plotly_white", height=140 + 45 * len(g),
                          xaxis=dict(range=[max(0, g["fr"].min() - 10), 105]),
                          margin=dict(l=10, r=30, t=50, b=30))
        st.plotly_chart(fig, width="stretch")
        if df["fecha"].nunique() > 1:
            d = df[df["estado"] != "ELIMINADA"].groupby("fecha", as_index=False).agg(
                sol=("sol_env", "sum"), dist=("dist_env", "sum"))
            d["fr"] = d["dist"] / d["sol"] * 100
            fig = go.Figure(go.Scatter(x=d["fecha"], y=d["fr"], mode="lines+markers",
                                       line=dict(color=BIMBO_BLUE, width=3)))
            fig.add_hline(y=META_FR, line_dash="dash", line_color=ROJO)
            fig.update_layout(title="Fill rate diario", template="plotly_white", height=300,
                              yaxis_title="%", margin=dict(l=10, r=10, t=50, b=30))
            st.plotly_chart(fig, width="stretch")
        st.caption("El detalle de quiebre por producto (qué producto y cuánta venta) está en el Excel "
                   "que deja el botón 3: hoja 'Quiebre por producto'.")
