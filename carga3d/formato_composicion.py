# =============================================================
# formato_composicion.py — Texto compacto de la carga de una sala
#
# Viaja en el campo custom_1 del pedido en Drivin. Este archivo NO
# depende de nada del proyecto: se puede copiar tal cual al repo de la
# app de monitoreo para decodificar.
#
# Formato: tramos separados por "|", campos por ":"
#   tipo_envase : envases : cupo_pallet : alto_pallet_full_m : n_codigos
# Ejemplo:
#   "BG:133:72:2.34:18|CG:20:25:1.55:2"
#   = 133 bandejas BG (72 por pallet, 2,34 m pallet full, 18 códigos)
#   +  20 cajas CG    (25 por pallet, 1,55 m pallet full,  2 códigos)
# =============================================================

SEP_TRAMO = "|"
SEP_CAMPO = ":"
VERSION = "v1"  # Prefijo para poder cambiar el formato a futuro sin romper la app


def familia_de(tipo_envase: str) -> str:
    """Regla del proyecto: tipo que parte con B = bandeja, con C = caja."""
    inicial = (tipo_envase or "").strip().upper()[:1]
    return {"B": "BANDEJA", "C": "CAJA"}.get(inicial, "OTRO")


def codificar(tramos: list[dict]) -> str:
    """Lista de tramos -> texto para custom_1."""
    partes = [
        SEP_CAMPO.join([
            str(t["tipo_envase"]),
            str(int(t["envases"])),
            f"{t['cupo_pallet']:.1f}".rstrip("0").rstrip("."),
            f"{t['alto_pallet_full_m']:.2f}",
            str(int(t["n_codigos"])),
        ])
        for t in tramos
    ]
    return VERSION + SEP_TRAMO + SEP_TRAMO.join(partes)


def decodificar(texto: str | None) -> list[dict]:
    """Texto de custom_1 -> lista de tramos. Devuelve [] si viene vacío o con otro formato."""
    if not texto or not str(texto).startswith(VERSION + SEP_TRAMO):
        return []
    tramos = []
    for parte in str(texto).split(SEP_TRAMO)[1:]:
        try:
            tipo, envases, cupo, alto, codigos = parte.split(SEP_CAMPO)
            tramos.append({
                "tipo_envase": tipo,
                "familia": familia_de(tipo),
                "envases": int(envases),
                "cupo_pallet": float(cupo),
                "alto_pallet_full_m": float(alto),
                "n_codigos": int(codigos),
            })
        except ValueError:
            continue  # Tramo mal formado: se ignora sin romper la app
    return tramos
