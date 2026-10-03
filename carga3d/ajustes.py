# =============================================================
# ajustes.py — Parámetros de la carga 3D (copia de config.py del
# proyecto Carga T2). Si cambias una regla allá, cámbiala aquí también.
# =============================================================

# Pallet (estándar T1/T2)
PALLET_LARGO_M = 1.30
PALLET_ANCHO_M = 1.20
ALTO_MAX_POR_FAMILIA_M = {"BANDEJA": 2.34, "CAJA": 1.80}

# Reglas de armado
UMBRAL_PALLET_PROPIO = 0.5          # Sala con >= medio pallet: pallets propios
FACTOR_MEZCLA = 0.90                # Capacidad de un pallet con cajas + bandejas
ORDEN_APILADO = ["BANDEJA", "CAJA"]  # De abajo hacia arriba

# Camión
POSICIONES_PALLET_DEFAULT = 8
BANDEJAS_POR_PALLET_REF = 72        # capacity_1 de Drivin (bandejas) / 72 = posiciones
PALLETS_POR_FILA = 2
ALTO_CAJA_CAMION_M = 2.40

# Dibujo
COLOR_FAMILIA = {"BANDEJA": "#2E86AB", "CAJA": "#F0A202"}
SEPARACION_PALLET_M = 0.06
