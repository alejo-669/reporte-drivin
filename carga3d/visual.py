# =============================================================
# visual.py — Dibujo 3D del camión (copia de visual_3d del proyecto Carga T2)
#   - Último cliente al fondo (cabina), primero junto a la puerta
#   - Cada pallet en tramos: cliente y envase, con su alto real
# =============================================================
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from . import ajustes as config


# -------------------------------------------------------------
# 1. Piezas geométricas
# -------------------------------------------------------------
def _bloque(x0, y0, z0, dx, dy, dz, color, nombre, hover, opacidad=1.0, leyenda=False, grupo=None):
    """Prisma rectangular sólido (Mesh3d) con texto al pasar el mouse."""
    x = [x0, x0 + dx, x0 + dx, x0, x0, x0 + dx, x0 + dx, x0]
    y = [y0, y0, y0 + dy, y0 + dy, y0, y0, y0 + dy, y0 + dy]
    z = [z0, z0, z0, z0, z0 + dz, z0 + dz, z0 + dz, z0 + dz]
    return go.Mesh3d(
        x=x, y=y, z=z,
        i=[0, 0, 4, 4, 0, 0, 1, 1, 2, 2, 3, 3],
        j=[1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 0, 4],
        k=[2, 3, 6, 7, 5, 4, 6, 5, 7, 6, 4, 7],
        color=color, opacity=opacidad, flatshading=True,
        name=nombre, showlegend=leyenda, legendgroup=grupo or nombre,
        hovertext=hover, hoverinfo="text",
    )


def _aristas(x0, y0, z0, dx, dy, dz, color="#333333", ancho=2):
    """Contorno de un prisma (12 aristas) como líneas."""
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    puntos = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z0),  # base
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1),  # techo
        (None, None, None), (x1, y0, z0), (x1, y0, z1),
        (None, None, None), (x1, y1, z0), (x1, y1, z1),
        (None, None, None), (x0, y1, z0), (x0, y1, z1),
    ]
    xs, ys, zs = zip(*puntos)
    return go.Scatter3d(x=xs, y=ys, z=zs, mode="lines",
                        line=dict(color=color, width=ancho),
                        hoverinfo="skip", showlegend=False)


# -------------------------------------------------------------
# 2. Posiciones en el camión
# -------------------------------------------------------------
def asignar_posiciones(pallets: pd.DataFrame, posiciones: int) -> pd.DataFrame:
    """Ordena pallets por visita inversa y les asigna fila/columna en la caja."""
    ordenados = pallets.sort_values(["orden_visita", "pallet_id"], ascending=[False, True]).copy()
    ordenados["posicion"] = range(len(ordenados))
    ordenados["fila"] = ordenados["posicion"] // config.PALLETS_POR_FILA
    ordenados["columna"] = ordenados["posicion"] % config.PALLETS_POR_FILA
    ordenados["fuera_de_cupo"] = ordenados["posicion"] >= posiciones
    return ordenados


# -------------------------------------------------------------
# 3. Figura
# -------------------------------------------------------------
def dibujar_camion(pallets: pd.DataFrame, detalle: pd.DataFrame,
                   posiciones: int = config.POSICIONES_PALLET_DEFAULT,
                   color_por: str = "cliente", titulo: str = "") -> go.Figure:
    """Figura 3D de un camión.

    pallets / detalle : salidas de calculo_pallets.armar_pallets para UNA ruta
    color_por         : "cliente" (ver secuencia) o "familia" (ver cajas vs bandejas)
    """
    largo_p, ancho_p = config.PALLET_LARGO_M, config.PALLET_ANCHO_M
    sep = config.SEPARACION_PALLET_M
    filas_camion = -(-posiciones // config.PALLETS_POR_FILA)  # División hacia arriba
    largo_caja = filas_camion * largo_p
    ancho_caja = config.PALLETS_POR_FILA * ancho_p
    alto_caja = config.ALTO_CAJA_CAMION_M

    ubicados = asignar_posiciones(pallets, posiciones)

    # Colores por cliente real (en orden de visita), también dentro de pallets compartidos
    clientes = detalle.sort_values("orden_visita")["cliente"].unique()
    paleta = px.colors.qualitative.Safe + px.colors.qualitative.Pastel
    color_cliente = {c: paleta[i % len(paleta)] for i, c in enumerate(clientes)}

    trazas = [_aristas(0, 0, 0, largo_caja, ancho_caja, alto_caja, "#7F8C8D", 3)]

    # Posiciones vacías: marca gris en el piso
    for pos in range(len(ubicados), posiciones):
        fila, col = divmod(pos, config.PALLETS_POR_FILA)
        trazas.append(_bloque(fila * largo_p + sep, col * ancho_p + sep, 0,
                              largo_p - 2 * sep, ancho_p - 2 * sep, 0.02,
                              "#BDC3C7", "Posición libre", "Posición libre", 0.6))

    leyenda_mostrada = set()
    for _, p in ubicados.iterrows():
        x0 = p["fila"] * largo_p + sep
        y0 = p["columna"] * ancho_p + sep
        dx, dy = largo_p - 2 * sep, ancho_p - 2 * sep

        # Tramos del pallet (cliente + envase). De abajo hacia arriba:
        #   1) último cliente en entregar abajo (solo importa en compartidos)
        #   2) dentro de cada cliente, según config.ORDEN_APILADO
        tramos = (detalle[detalle["pallet_id"] == p["pallet_id"]]
                  .groupby(["cliente", "orden_visita", "familia"], as_index=False)
                  .agg(alto=("alto_ocupado_m", "sum"), envases=("envases", "sum"),
                       codigos=("n_codigos", "sum")))
        tramos["nivel"] = tramos["familia"].map(
            {f: i for i, f in enumerate(config.ORDEN_APILADO)}).fillna(99)
        tramos = tramos.sort_values(["orden_visita", "nivel"], ascending=[False, True])

        z = 0.0
        for _, t in tramos.iterrows():
            if color_por == "familia":
                color, nombre = config.COLOR_FAMILIA.get(t["familia"], "#95A5A6"), t["familia"]
            else:
                color = color_cliente[t["cliente"]]
                nombre = f"{int(t['orden_visita'])}. {t['cliente']}"
            if p["fuera_de_cupo"]:
                color = "#E74C3C"  # Rojo: no cabe en el camión

            hover = (f"<b>{t['cliente']}</b> (visita {int(t['orden_visita'])})<br>"
                     f"Pallet {p['pallet_id']} ({p['tipo_pallet'].lower()}) · {t['familia']}<br>"
                     f"{int(t['envases'])} envases · {int(t['codigos'])} códigos<br>"
                     f"Ocupación pallet: {p['ocupacion_pct']:.0f}%")
            if p["fuera_de_cupo"]:
                hover += "<br><b>⚠ FUERA DE CUPO</b>"

            mostrar = nombre not in leyenda_mostrada
            leyenda_mostrada.add(nombre)
            trazas.append(_bloque(x0, y0, z, dx, dy, t["alto"], color, nombre, hover,
                                  leyenda=mostrar, grupo=nombre))
            z += t["alto"]

        trazas.append(_aristas(x0, y0, 0, dx, dy, z, "#2C3E50", 2))

    # Cabina del camión (bloque gris de referencia)
    trazas.append(_bloque(-1.3, 0.1, 0, 1.15, ancho_caja - 0.2, alto_caja * 0.8,
                          "#95A5A6", "Cabina", "Cabina", opacidad=0.35))

    # Etiquetas de orientación a nivel del piso, fuera de la carga
    trazas.append(go.Scatter3d(
        x=[-0.7, largo_caja + 0.5], y=[ancho_caja / 2] * 2, z=[alto_caja * 0.8 + 0.25, 0.1],
        mode="text", text=["<b>CABINA</b>", "<b>PUERTA</b>"],
        textfont=dict(size=14, color="#1B2A49"),
        hoverinfo="skip", showlegend=False))

    fig = go.Figure(trazas)
    fig.update_layout(
        title=dict(text=titulo, font=dict(color="#1B2A49", size=18)),
        scene=dict(
            xaxis=dict(title="Largo (m)", range=[-1.5, largo_caja + 1.0]),
            yaxis=dict(title="Ancho (m)", range=[-0.3, ancho_caja + 0.3]),
            zaxis=dict(title="Alto (m)", range=[0, alto_caja + 0.2]),
            aspectmode="data",
            camera=dict(eye=dict(x=1.4, y=-1.6, z=1.0)),
        ),
        legend=dict(title="Cliente (orden de visita)" if color_por == "cliente" else "Envase"),
        margin=dict(l=0, r=0, t=50, b=0),
        height=650,
    )
    return fig
