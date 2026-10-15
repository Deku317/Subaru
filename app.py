"""
subaru.py — Dashboard ejecutivo del Sistema de Análisis Financiero para Aseguradoras
Ejecutar:  streamlit run subaru.py

Flujo:
    PDF -> ExtractorFinanciero.cargar_pdf_hibrido() + ejecutar_extraccion_completa()  -> dict de cuentas
        -> (What-If en sidebar) -> dict simulado
        -> AnalizadorFinanciero.ejecutar_analisis_completo()  -> 20 razones + diagnósticos
        -> KPIs, gráficas e insights
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from Gate import ExtractorFinanciero
from analisis import AnalizadorFinanciero

st.set_page_config(
    page_title="Análisis Financiero · Aseguradoras",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CATÁLOGO DE RAZONES (las 20 que calcula analisis.py)
# formato: "pct" (fracción -> %), "x" (veces), "mon" (monto)
# mayor_mejor: True / False / None (neutral, sin color en el delta)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Razon:
    categoria: str
    clave: str
    etiqueta: str
    formato: str
    mayor_mejor: bool | None


CATALOGO: list[Razon] = [
    # Liquidez
    Razon("Liquidez", "Razon_1", "Activo circulante / Pasivo circulante", "x", True),
    Razon("Liquidez", "Razon_2", "Inversiones / Pasivo exigible", "x", True),
    Razon("Liquidez", "Razon_3", "Activo circulante / Pasivo exigible", "x", True),
    Razon("Liquidez", "Razon_4", "Activo circulante / Reservas técnicas", "x", True),
    Razon("Liquidez", "Razon_5", "Inversiones / Pasivo circulante", "x", True),
    # Solvencia y apalancamiento
    Razon("Solvencia_Apalancamiento", "Solvencia_1", "Activo total / Pasivo total", "x", True),
    Razon("Solvencia_Apalancamiento", "Solvencia_2", "(Activo − Activo fijo) / (Pasivo − Reservas)", "x", True),
    Razon("Solvencia_Apalancamiento", "Apalancamiento_1", "Pasivo total / Capital contable", "x", False),
    Razon("Solvencia_Apalancamiento", "Apalancamiento_2", "Reservas técnicas / Capital contable", "x", False),
    # Suficiencia de prima
    Razon("Suficiencia_Prima", "Cto_Medio_Operacion", "Costo medio de operación", "pct", False),
    Razon("Suficiencia_Prima", "Cto_Medio_Adquisicion", "Costo medio de adquisición", "pct", False),
    Razon("Suficiencia_Prima", "Cto_Medio_Siniestralidad", "Costo medio de siniestralidad", "pct", False),
    Razon("Suficiencia_Prima", "Indice_Combinado", "Índice combinado", "pct", False),
    Razon("Suficiencia_Prima", "Suficiencia_Prima", "Suficiencia de prima", "pct", True),
    # Reaseguro
    Razon("Reaseguro", "Razon_1_Cesion", "Prima cedida / Prima emitida", "pct", None),
    Razon("Reaseguro", "Razon_2_Retencion", "Prima retenida / Prima emitida", "pct", None),
    Razon("Reaseguro", "Razon_3_Comision", "Comisión reaseguro / Prima cedida", "pct", None),
    # Rentabilidad
    Razon("Rentabilidad", "Razon_1_ROE", "ROE (Utilidad / Capital contable)", "pct", True),
    Razon("Rentabilidad", "Razon_2_Cap_Pagado", "Utilidad / Capital pagado", "pct", True),
    Razon("Rentabilidad", "Razon_3_Margen_Primas", "Margen (Utilidad / Prima directa)", "pct", True),
]
INDICE: dict[tuple[str, str], Razon] = {(r.categoria, r.clave): r for r in CATALOGO}

NOMBRES_CATEGORIA = {
    "Liquidez": "Liquidez",
    "Solvencia_Apalancamiento": "Solvencia y apalancamiento",
    "Suficiencia_Prima": "Suficiencia de prima",
    "Reaseguro": "Reaseguro",
    "Rentabilidad": "Rentabilidad",
}

# KPIs principales: (título, (categoría, clave), ayuda)
KPIS = [
    ("Suficiencia de prima", ("Suficiencia_Prima", "Suficiencia_Prima"),
     "1 − Índice combinado. Positivo = rentable técnicamente."),
    ("ROE", ("Rentabilidad", "Razon_1_ROE"), "Utilidad neta / Capital contable."),
    ("Índice de liquidez", ("Liquidez", "Razon_1"), "Activo circulante / Pasivo circulante."),
    ("Siniestralidad", ("Suficiencia_Prima", "Cto_Medio_Siniestralidad"),
     "Costo de siniestralidad / Prima retenida devengada. Menor es mejor."),
]

# Cuentas del diccionario de Gate.py que el usuario puede simular
VARIABLES_WHATIF = {
    "prima_emitida": "Prima emitida",
    "costo_siniestralidad": "Costo de siniestralidad",
    "costo_operacion": "Gastos de operación (netos)",
    "activo_circulante": "Activo circulante",
    "pasivo_circulante": "Pasivo circulante",
}

# Cuentas que se reescalan cuando cambia la prima emitida (opcional, toggle)
CUENTAS_ESCALABLES = ("prima_retenida", "prima_cedida", "prima_re_devengadas",
                      "comision_re_cedido", "costo_netoa")
# Gate.py extrae prima_directa con la misma cuenta que prima_emitida: siempre se sincroniza
CUENTAS_SIEMPRE_SINCRONIZADAS = ("prima_directa",)

# Umbrales de referencia para el medidor de liquidez
LIQUIDEZ_CRITICA = 1.0
LIQUIDEZ_ADECUADA = 1.5

COLOR_REAL = "#6B7280"
COLOR_SIM = "#2563EB"

CSS = """
<style>
    .block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,.25);
        border-radius: 12px;
        padding: 14px 18px;
    }
    h1 {font-size: 2rem !important; margin-bottom: 0 !important;}
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────
def a_numero(valor: Any) -> float | None:
    """Devuelve float si es numérico; None si es None o texto (p. ej. 'Error (#DIV/0!)')."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    return None


def fmt_valor(valor: float | None, formato: str) -> str:
    if valor is None:
        return "N/D"
    if formato == "pct":
        return f"{valor * 100:,.2f}%"
    if formato == "x":
        return f"{valor:,.2f}x"
    return f"{valor:,.0f}"


def fmt_delta(delta: float, formato: str) -> str:
    if formato == "pct":
        return f"{delta * 100:+,.2f} pp"
    if formato == "x":
        return f"{delta:+,.2f}x"
    return f"{delta:+,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# BACKEND: EXTRACCIÓN Y ANÁLISIS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Extrayendo cuentas del PDF…")
def extraer_datos_pdf(contenido: bytes, paginas_dos_columnas: tuple[int, ...]) -> dict:
    """PDF subido -> archivo temporal -> ExtractorFinanciero -> dict de cuentas."""
    ruta = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(contenido)
            ruta = tmp.name

        extractor = ExtractorFinanciero(ruta)
        extractor.cargar_pdf_hibrido(paginas_dos_columnas=list(paginas_dos_columnas))
        # cargar_pdf_hibrido captura sus propias excepciones; sin líneas no hay nada que analizar
        if not extractor.lineas_texto:
            raise ValueError("No se pudo leer texto del PDF (¿está escaneado o dañado?).")
        return extractor.ejecutar_extraccion_completa()
    finally:
        if ruta and os.path.exists(ruta):
            os.remove(ruta)


@dataclass
class Resultado:
    valores: dict[tuple[str, str], float | None] = field(default_factory=dict)
    pendientes: list[str] = field(default_factory=list)          # razones no calculables
    diagnosticos: list[tuple[str, str]] = field(default_factory=list)  # (categoría, texto)


def analizar(datos: dict) -> Resultado:
    """Ejecuta AnalizadorFinanciero y aplana su reporte {categoría: {razón: valor, Diagnostico: texto}}."""
    reporte = AnalizadorFinanciero(dict(datos)).ejecutar_analisis_completo()
    res = Resultado()
    for categoria, bloque in reporte.items():
        if not isinstance(bloque, dict):
            continue
        for clave, valor in bloque.items():
            if clave == "Diagnostico":
                res.diagnosticos.append((categoria, str(valor)))
                continue
            numero = a_numero(valor)
            res.valores[(categoria, clave)] = numero
            if numero is None:
                razon = INDICE.get((categoria, clave))
                nombre = razon.etiqueta if razon else clave
                detalle = f" — {valor}" if isinstance(valor, str) else ""
                res.pendientes.append(f"{NOMBRES_CATEGORIA.get(categoria, categoria)} · {nombre}{detalle}")
    return res


# ─────────────────────────────────────────────────────────────────────────────
# ESCENARIO WHAT-IF
# ─────────────────────────────────────────────────────────────────────────────
def construir_escenario(datos_real: dict, entradas: dict, escalar: bool, propagar: bool) -> dict:
    """
    Parte de los datos reales y aplica las entradas del usuario.
      - escalar:   reescala primas retenida/cedida/devengada, comisión y costo de adquisición
                   en la misma proporción que la prima emitida.
      - propagar:  ajusta la utilidad neta por el cambio en primas devengadas y costos
                   (analisis.py toma la utilidad como dato, no la deriva de las demás cuentas).
    """
    sim = dict(datos_real)
    sim.update(entradas)

    base = a_numero(datos_real.get("prima_emitida"))
    nueva = a_numero(sim.get("prima_emitida"))
    if base and nueva is not None:
        factor = nueva / base
        cuentas = CUENTAS_SIEMPRE_SINCRONIZADAS + (CUENTAS_ESCALABLES if escalar else ())
        for cuenta in cuentas:
            valor = a_numero(datos_real.get(cuenta))
            if valor is not None:
                sim[cuenta] = valor * factor

    if propagar:
        utilidad = a_numero(datos_real.get("utilidad_neta"))
        if utilidad is not None:
            def cambio(k: str) -> float:
                return (a_numero(sim.get(k)) or 0.0) - (a_numero(datos_real.get(k)) or 0.0)

            sim["utilidad_neta"] = (
                utilidad
                + cambio("prima_re_devengadas")
                - cambio("costo_siniestralidad")
                - cambio("costo_operacion")
                - cambio("costo_netoa")
            )
    return sim


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
def _reiniciar_simulador() -> None:
    st.session_state["version_sim"] = st.session_state.get("version_sim", 0) + 1


def _parsear_paginas(texto: str) -> tuple[int, ...]:
    """'1, 3' (numeración humana) -> (0, 2) (índices de pdfplumber)."""
    try:
        paginas = sorted({int(p) - 1 for p in texto.replace(" ", "").split(",") if p})
        return tuple(p for p in paginas if p >= 0) or (0,)
    except ValueError:
        st.warning("Formato de páginas inválido; se usará la página 1.")
        return (0,)


def render_sidebar() -> tuple[dict | None, dict | None]:
    """Devuelve (datos_reales, datos_simulados) o (None, None) si aún no hay PDF."""
    st.session_state.setdefault("version_sim", 0)

    with st.sidebar:
        st.header("⚙️ Panel de control")
        archivo = st.file_uploader("Sube el estado financiero (PDF)", type=["pdf"])

        with st.expander("Opciones de lectura del PDF"):
            texto_paginas = st.text_input(
                "Páginas con dos columnas (Balance General)",
                value="1",
                help="Numeración desde 1, separadas por coma. El resto se lee a una columna.",
            )

        if archivo is None:
            st.info("Sube un PDF para activar el análisis y el simulador.")
            return None, None

        contenido = archivo.getvalue()
        id_archivo = hashlib.md5(contenido).hexdigest()[:8]

        try:
            datos_real = extraer_datos_pdf(contenido, _parsear_paginas(texto_paginas))
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudo procesar el PDF: {exc}")
            return None, None

        st.success(f"✅ {archivo.name}")
        st.divider()
        st.subheader("🧪 Simulador (What-If)")
        st.caption("Modifica los valores y todo el dashboard se recalcula al instante.")

        entradas: dict[str, float] = {}
        for clave, etiqueta in VARIABLES_WHATIF.items():
            base = a_numero(datos_real.get(clave))
            if base is None:
                st.caption(f"⚠️ «{etiqueta}» no se detectó en el PDF.")
                continue
            entradas[clave] = st.number_input(
                etiqueta,
                value=base,
                step=max(abs(base) * 0.01, 1.0),
                format="%.2f",
                key=f"sim_{id_archivo}_{st.session_state['version_sim']}_{clave}",
            )

        escalar = st.toggle(
            "Escalar primas y costo de adquisición con la prima emitida",
            value=True,
            help="Al cambiar la prima emitida, mantiene constantes las proporciones de prima "
                 "retenida, cedida, devengada, comisión de reaseguro y costo neto de adquisición.",
        )
        propagar = st.toggle(
            "Propagar el impacto a la utilidad neta",
            value=True,
            help="analisis.py toma la utilidad neta como dato fijo. Con esto se ajusta por el "
                 "cambio en primas devengadas, siniestralidad, gastos de operación y adquisición "
                 "(simplificación: no considera impuestos ni PTU).",
        )
        st.button("↺ Restablecer valores", on_click=_reiniciar_simulador, use_container_width=True)

        # El explorador (sensibilidad / mapa 2D) recalcula escenarios con los mismos criterios
        st.session_state["cfg_escenario"] = (escalar, propagar)

        with st.expander("🎨 Opciones de gráficas"):
            st.selectbox("Tema de gráficas", TEMAS, key="tema_graficas")
            st.slider("Altura del explorador (px)", 300, 800, 450, step=25, key="altura_explorador")

        datos_sim = construir_escenario(datos_real, entradas, escalar, propagar)

        u_real, u_sim = a_numero(datos_real.get("utilidad_neta")), a_numero(datos_sim.get("utilidad_neta"))
        if propagar and u_real is not None and u_sim is not None and abs(u_sim - u_real) > 1e-9:
            st.caption(f"Utilidad neta simulada: {u_sim:,.0f} (real: {u_real:,.0f})")

        return datos_real, datos_sim


# ─────────────────────────────────────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────────────────────────────────────
def _metric(col, etiqueta: str, v_sim: float | None, v_real: float | None,
            formato: str, mayor_mejor: bool | None, ayuda: str) -> None:
    ayuda_completa = f"{ayuda}\n\nValor real (PDF): {fmt_valor(v_real, formato)}"
    if v_sim is None:
        col.metric(etiqueta, "N/D", help=ayuda_completa)
        return
    if v_real is None:
        col.metric(etiqueta, fmt_valor(v_sim, formato), help=ayuda_completa)
        return

    delta = v_sim - v_real
    if abs(delta) < 1e-9:
        col.metric(etiqueta, fmt_valor(v_sim, formato), delta=fmt_delta(0.0, formato).lstrip("+"),
                   delta_color="off", help=ayuda_completa)
        return

    if mayor_mejor is None:
        color = "off"
    else:
        # "normal": sube = verde / baja = rojo. "inverse": al revés (costos, apalancamiento).
        color = "normal" if mayor_mejor else "inverse"
    col.metric(etiqueta, fmt_valor(v_sim, formato), delta=fmt_delta(delta, formato),
               delta_color=color, help=ayuda_completa)


def render_kpis(real: Resultado, sim: Resultado, datos_real: dict, datos_sim: dict) -> None:
    st.subheader("Indicadores clave")
    columnas = st.columns(len(KPIS) + 1)

    for col, (etiqueta, ruta, ayuda) in zip(columnas, KPIS):
        razon = INDICE[ruta]
        _metric(col, etiqueta, sim.valores.get(ruta), real.valores.get(ruta),
                razon.formato, razon.mayor_mejor, ayuda)

    _metric(columnas[-1], "Utilidad neta", a_numero(datos_sim.get("utilidad_neta")),
            a_numero(datos_real.get("utilidad_neta")), "mon", True,
            "Dato extraído del PDF. En el simulador se ajusta si activas la propagación.")


# ─────────────────────────────────────────────────────────────────────────────
# GRÁFICAS
# ─────────────────────────────────────────────────────────────────────────────
def grafica_composicion_prima(datos: dict) -> go.Figure | None:
    emitida = a_numero(datos.get("prima_emitida"))
    retenida = a_numero(datos.get("prima_retenida"))
    cedida = a_numero(datos.get("prima_cedida"))

    if retenida is None and emitida is not None and cedida is not None:
        retenida = emitida - cedida
    if cedida is None and emitida is not None and retenida is not None:
        cedida = emitida - retenida
    if retenida is None or cedida is None or retenida < 0 or cedida < 0 or (retenida + cedida) <= 0:
        return None

    df = pd.DataFrame({"Concepto": ["Retenida", "Cedida"], "Monto": [retenida, cedida]})
    fig = px.pie(
        df, names="Concepto", values="Monto", hole=0.5,
        color="Concepto", color_discrete_map={"Retenida": COLOR_SIM, "Cedida": "#F59E0B"},
    )
    fig.update_traces(textinfo="percent+label", hovertemplate="%{label}: %{value:,.0f}<extra></extra>")
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False, height=340)
    return fig


def grafica_gauge_liquidez(v_sim: float | None, v_real: float | None) -> go.Figure | None:
    if v_sim is None:
        return None
    maximo = max(3.0, v_sim * 1.4, (v_real or 0.0) * 1.4)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=v_sim,
            number={"suffix": "x"},
            delta={"reference": v_real if v_real is not None else v_sim,
                   "increasing": {"color": "#16A34A"}, "decreasing": {"color": "#DC2626"}},
            gauge={
                "axis": {"range": [0, maximo]},
                "bar": {"color": COLOR_SIM},
                "steps": [
                    {"range": [0, LIQUIDEZ_CRITICA], "color": "rgba(220,38,38,.30)"},
                    {"range": [LIQUIDEZ_CRITICA, LIQUIDEZ_ADECUADA], "color": "rgba(245,158,11,.30)"},
                    {"range": [LIQUIDEZ_ADECUADA, maximo], "color": "rgba(22,163,74,.30)"},
                ],
                "threshold": {"line": {"color": "black", "width": 3}, "value": LIQUIDEZ_CRITICA},
            },
        )
    )
    fig.update_layout(margin=dict(t=30, b=10, l=30, r=30), height=340)
    return fig


def grafica_comparativo(real: Resultado, sim: Resultado, categoria: str) -> go.Figure | None:
    """Barras agrupadas real vs. simulado para una categoría (todas sus razones comparten unidad)."""
    filas = []
    for razon in (r for r in CATALOGO if r.categoria == categoria):
        escala = 100 if razon.formato == "pct" else 1
        ruta = (razon.categoria, razon.clave)
        for escenario, resultado in (("Real (PDF)", real), ("Simulado", sim)):
            valor = resultado.valores.get(ruta)
            if valor is not None:
                filas.append({"Razón": razon.etiqueta, "Escenario": escenario, "Valor": valor * escala})
    if not filas:
        return None

    unidad = "%" if INDICE[next(k for k in INDICE if k[0] == categoria)].formato == "pct" else "veces"
    fig = px.bar(
        pd.DataFrame(filas), x="Razón", y="Valor", color="Escenario", barmode="group",
        color_discrete_map={"Real (PDF)": COLOR_REAL, "Simulado": COLOR_SIM}, text_auto=".2f",
    )
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=400,
                      legend_title_text="", yaxis_title=unidad)
    return fig


def render_graficas(datos_sim: dict, real: Resultado, sim: Resultado) -> None:
    st.subheader("Relación entre indicadores")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Composición de prima (escenario simulado)**")
        fig_pie = grafica_composicion_prima(datos_sim)
        if fig_pie:
            mostrar(fig_pie, key="pastel_prima")
        else:
            st.info("No se detectaron prima retenida/cedida suficientes para graficar.")

    with col_b:
        st.markdown("**Índice de liquidez (Activo circulante / Pasivo circulante)**")
        ruta = ("Liquidez", "Razon_1")
        fig_gauge = grafica_gauge_liquidez(sim.valores.get(ruta), real.valores.get(ruta))
        if fig_gauge:
            mostrar(fig_gauge, key="gauge_liquidez")
            st.caption(f"Zonas: rojo < {LIQUIDEZ_CRITICA} · ámbar < {LIQUIDEZ_ADECUADA} · verde ≥ {LIQUIDEZ_ADECUADA}")
        else:
            st.info("No fue posible calcular la liquidez con los datos extraídos.")

    st.markdown("**Comparativo de razones: real vs. simulado**")
    categoria = st.selectbox(
        "Categoría", list(NOMBRES_CATEGORIA), format_func=NOMBRES_CATEGORIA.get, index=2,
    )
    fig_bar = grafica_comparativo(real, sim, categoria)
    if fig_bar:
        mostrar(fig_bar, key="barras_categoria")
    else:
        st.info("Ninguna razón de esta categoría pudo calcularse con los datos extraídos.")


# ─────────────────────────────────────────────────────────────────────────────
# INSIGHTS
# ─────────────────────────────────────────────────────────────────────────────
def clasificar(texto: str) -> str:
    """Asigna severidad a los textos de diagnóstico de analisis.py."""
    t = texto.lower()
    if any(p in t for p in ("alerta", "pérdida", "perdida", "crítico", "critico", "insolven")):
        return "error"
    if any(p in t for p in ("faltan datos", "precaución", "atención", "deterioro", "riesgo")):
        return "warning"
    if any(p in t for p in ("rentable", "positivo", "saludable", "adecuad", "favorable")):
        return "success"
    return "info"


def _tarjetas(res: Resultado) -> None:
    iconos = {"error": "🚨", "warning": "⚠️", "success": "✅", "info": "ℹ️"}
    if not res.diagnosticos:
        st.info("El análisis no devolvió diagnósticos de texto.")
    for categoria, texto in res.diagnosticos:
        nivel = clasificar(texto)
        getattr(st, nivel)(f"**{NOMBRES_CATEGORIA.get(categoria, categoria)}:** {texto}", icon=iconos[nivel])

    if res.pendientes:
        with st.expander(f"⚠️ {len(res.pendientes)} razón(es) no calculable(s) con los datos extraídos"):
            for p in res.pendientes:
                st.markdown(f"- {p}")


def render_insights(real: Resultado, sim: Resultado) -> None:
    st.subheader("Insights y diagnóstico automático")
    tab_sim, tab_real = st.tabs(["Escenario simulado", "Datos reales (PDF)"])
    with tab_sim:
        _tarjetas(sim)
    with tab_real:
        _tarjetas(real)


# ─────────────────────────────────────────────────────────────────────────────
# DETALLE
# ─────────────────────────────────────────────────────────────────────────────
def render_detalle(datos_real: dict, datos_sim: dict, real: Resultado, sim: Resultado) -> None:
    with st.expander("📋 Detalle completo: 20 razones y cuentas extraídas"):
        tab_r, tab_c = st.tabs(["Razones financieras", "Cuentas extraídas"])
        with tab_r:
            filas = []
            for r in CATALOGO:
                ruta = (r.categoria, r.clave)
                v_real, v_sim = real.valores.get(ruta), sim.valores.get(ruta)
                var = fmt_delta(v_sim - v_real, r.formato) if v_real is not None and v_sim is not None else "—"
                filas.append({
                    "Categoría": NOMBRES_CATEGORIA[r.categoria], "Razón": r.etiqueta,
                    "Real (PDF)": fmt_valor(v_real, r.formato),
                    "Simulado": fmt_valor(v_sim, r.formato), "Variación": var,
                })
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
        with tab_c:
            filas = [
                {"Cuenta": k, "Real (PDF)": a_numero(v), "Simulado": a_numero(datos_sim.get(k))}
                for k, v in datos_real.items()
            ]
            st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# EXPLORADOR AVANZADO (visualización libre para usuarios expertos)
# ─────────────────────────────────────────────────────────────────────────────
TEMA_DEFECTO = "Streamlit (predeterminado)"
TEMAS = [TEMA_DEFECTO, "plotly", "plotly_white", "plotly_dark", "simple_white",
         "ggplot2", "seaborn", "presentation"]
COLORES_ESCENARIO = {"Real (PDF)": COLOR_REAL, "Simulado": COLOR_SIM}
TIPOS_GRAFICA = ["Barras", "Barras horizontales", "Líneas", "Área", "Puntos",
                 "Dona", "Treemap", "Embudo"]
TIPOS_COMPOSICION = {"Dona", "Treemap", "Embudo"}

RUTAS_CASCADA = [
    ("Suficiencia_Prima", "Cto_Medio_Siniestralidad"),
    ("Suficiencia_Prima", "Cto_Medio_Adquisicion"),
    ("Suficiencia_Prima", "Cto_Medio_Operacion"),
]


def mostrar(fig: go.Figure, altura: int | None = None, key: str | None = None) -> None:
    """Muestra una figura aplicando el tema elegido en el sidebar y la barra de exportación."""
    tema = st.session_state.get("tema_graficas", TEMA_DEFECTO)
    if altura:
        fig.update_layout(height=altura)
    if tema != TEMA_DEFECTO:
        fig.update_layout(template=tema)
    st.plotly_chart(
        fig,
        use_container_width=True,
        theme="streamlit" if tema == TEMA_DEFECTO else None,
        key=key,
        config={"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}},
    )


def etiqueta_razon(r: Razon) -> str:
    return f"{NOMBRES_CATEGORIA[r.categoria]} · {r.etiqueta}"


OPCIONES_RAZON: dict[str, Razon] = {etiqueta_razon(r): r for r in CATALOGO}


def escala(r: Razon) -> float:
    return 100.0 if r.formato == "pct" else 1.0


def unidad(r: Razon) -> str:
    return "%" if r.formato == "pct" else "veces"


def variables_disponibles(datos_real: dict) -> dict[str, str]:
    return {k: lbl for k, lbl in VARIABLES_WHATIF.items() if a_numero(datos_real.get(k)) is not None}


def valor_objetivo(datos_real: dict, entradas: dict, ruta: tuple[str, str]) -> float | None:
    """Valor de una razón bajo un conjunto de entradas (respeta los toggles del simulador)."""
    escalar, propagar = st.session_state.get("cfg_escenario", (True, True))
    try:
        return analizar(construir_escenario(datos_real, entradas, escalar, propagar)).valores.get(ruta)
    except Exception:  # noqa: BLE001  (p. ej. datos faltantes en el backend)
        return None


# ── 1. Constructor libre ─────────────────────────────────────────────────────
def _df_constructor(fuente: str, seleccion: list[str], escenarios: list[str], normalizar: bool,
                    datos_real: dict, datos_sim: dict, real: Resultado, sim: Resultado) -> pd.DataFrame:
    filas = []
    for nombre in seleccion:
        if fuente == "Razones financieras":
            r = OPCIONES_RAZON[nombre]
            ruta = (r.categoria, r.clave)
            valores = {"Real (PDF)": real.valores.get(ruta), "Simulado": sim.valores.get(ruta)}
            factor, nombre_corto = escala(r), r.etiqueta
        else:
            valores = {"Real (PDF)": a_numero(datos_real.get(nombre)),
                       "Simulado": a_numero(datos_sim.get(nombre))}
            factor, nombre_corto = 1.0, nombre
        for esc in escenarios:
            valor = valores[esc]
            if valor is None:
                continue
            if normalizar:
                base = valores["Real (PDF)"]
                if not base:
                    continue
                valor = valor / base * 100
            else:
                valor *= factor
            filas.append({"Variable": nombre_corto, "Escenario": esc, "Valor": valor})
    return pd.DataFrame(filas, columns=["Variable", "Escenario", "Valor"])


def _figura_libre(df: pd.DataFrame, tipo: str, etiquetas: bool, log: bool,
                  ordenar: bool, titulo_eje: str) -> go.Figure:
    orden = None
    if ordenar:
        orden = {"Variable": df.groupby("Variable")["Valor"].max().sort_values(ascending=False).index.tolist()}
    kw = dict(color="Escenario", color_discrete_map=COLORES_ESCENARIO, category_orders=orden)

    if tipo == "Barras":
        fig = px.bar(df, x="Variable", y="Valor", barmode="group", log_y=log, **kw)
        if etiquetas:
            fig.update_traces(texttemplate="%{y:,.2f}", textposition="outside")
        fig.update_layout(yaxis_title=titulo_eje)
    elif tipo == "Barras horizontales":
        fig = px.bar(df, x="Valor", y="Variable", orientation="h", barmode="group", log_x=log, **kw)
        if etiquetas:
            fig.update_traces(texttemplate="%{x:,.2f}", textposition="outside")
        fig.update_layout(xaxis_title=titulo_eje)
    else:  # Líneas, Área, Puntos
        fig = px.line(df, x="Variable", y="Valor", markers=True, log_y=log, **kw)
        if tipo == "Área":
            fig.update_traces(fill="tozeroy")
        elif tipo == "Puntos":
            fig.update_traces(mode="markers", marker=dict(size=12))
        if etiquetas:
            modo = "markers+text" if tipo == "Puntos" else "lines+markers+text"
            fig.update_traces(mode=modo, texttemplate="%{y:,.2f}", textposition="top center")
        fig.update_layout(yaxis_title=titulo_eje)
    fig.update_layout(legend_title_text="", margin=dict(t=30, b=10, l=10, r=10))
    return fig


def _figura_composicion(d: pd.DataFrame, tipo: str) -> go.Figure:
    if tipo == "Dona":
        fig = px.pie(d, names="Variable", values="Valor", hole=0.45)
        fig.update_traces(textinfo="percent+label")
    elif tipo == "Treemap":
        fig = px.treemap(d, path=["Variable"], values="Valor")
        fig.update_traces(textinfo="label+value+percent root")
    else:
        fig = px.funnel(d.sort_values("Valor", ascending=False), x="Valor", y="Variable")
    fig.update_layout(margin=dict(t=30, b=10, l=10, r=10), showlegend=False)
    return fig


def tab_constructor(datos_real: dict, datos_sim: dict, real: Resultado, sim: Resultado, altura: int) -> None:
    c1, c2, c3 = st.columns([1.3, 1.3, 1])
    fuente = c1.radio("Fuente de datos", ["Razones financieras", "Cuentas extraídas"], horizontal=True)
    escenario = c2.radio("Escenario", ["Real (PDF)", "Simulado", "Ambos"], index=2, horizontal=True)
    tipo = c3.selectbox("Tipo de gráfica", TIPOS_GRAFICA)

    if fuente == "Razones financieras":
        opciones = list(OPCIONES_RAZON)
        defecto = [etiqueta_razon(INDICE[("Suficiencia_Prima", k)]) for k in (
            "Cto_Medio_Operacion", "Cto_Medio_Adquisicion", "Cto_Medio_Siniestralidad", "Suficiencia_Prima")]
        clave_sel = "sel_razones"
    else:
        opciones = [k for k, v in datos_real.items() if a_numero(v) is not None]
        defecto = [k for k in ("prima_emitida", "prima_cedida", "prima_retenida", "costo_siniestralidad")
                   if k in opciones] or opciones[:3]
        firma = hashlib.md5("|".join(opciones).encode()).hexdigest()[:6]
        clave_sel = f"sel_cuentas_{firma}"
    seleccion = st.multiselect("Variables a graficar", opciones, default=defecto, key=clave_sel)

    o1, o2, o3, o4 = st.columns(4)
    etiquetas = o1.checkbox("Mostrar valores", value=True)
    ordenar = o2.checkbox("Ordenar de mayor a menor", value=False)
    log = o3.checkbox("Escala logarítmica", value=False, help="Solo aplica a barras, líneas, área y puntos.")
    normalizar = o4.checkbox("Normalizar (Real = 100)", value=False,
                             help="Expresa cada variable como índice respecto al valor real del PDF.")

    if not seleccion:
        st.info("Selecciona al menos una variable.")
        return

    escenarios = ["Real (PDF)", "Simulado"] if escenario == "Ambos" else [escenario]
    df = _df_constructor(fuente, seleccion, escenarios, normalizar, datos_real, datos_sim, real, sim)
    if df.empty:
        st.warning("Ninguna de las variables elegidas tiene valor calculable.")
        return

    if tipo in TIPOS_COMPOSICION:
        columnas = st.columns(len(escenarios))
        for col, esc in zip(columnas, escenarios):
            d = df[(df["Escenario"] == esc) & (df["Valor"] > 0)]
            with col:
                st.markdown(f"**{esc}**")
                if d.empty:
                    st.info("Sin valores positivos para este tipo de gráfica.")
                    continue
                if len(d) < len(df[df["Escenario"] == esc]):
                    st.caption("Se omitieron valores ≤ 0.")
                mostrar(_figura_composicion(d, tipo), altura, key=f"libre_{tipo}_{esc}")
    else:
        if log and (df["Valor"] <= 0).any():
            st.caption("⚠️ La escala logarítmica omite los valores ≤ 0.")
        if normalizar:
            titulo_eje = "Índice (Real = 100)"
        elif fuente == "Razones financieras":
            titulo_eje = "% o veces, según la razón"
        else:
            titulo_eje = "Monto"
        mostrar(_figura_libre(df, tipo, etiquetas, log, ordenar, titulo_eje), altura, key=f"libre_{tipo}")


# ── 2. Radar ─────────────────────────────────────────────────────────────────
def tab_radar(real: Resultado, sim: Resultado, altura: int) -> None:
    opciones = list(OPCIONES_RAZON)
    defecto = [etiqueta_razon(INDICE[r]) for r in (
        ("Liquidez", "Razon_1"), ("Solvencia_Apalancamiento", "Solvencia_1"),
        ("Suficiencia_Prima", "Suficiencia_Prima"), ("Rentabilidad", "Razon_1_ROE"),
        ("Reaseguro", "Razon_2_Retencion"))]
    c1, c2 = st.columns([3, 1])
    seleccion = c1.multiselect("Razones (mínimo 3)", opciones, default=defecto, key="radar_sel")
    normalizar = c2.checkbox("Normalizar (Real = 100)", value=True, key="radar_norm",
                             help="Pone todos los ejes en la misma escala: el polígono real es un círculo en 100.")

    ejes, v_real, v_sim = [], [], []
    for nombre in seleccion:
        r = OPCIONES_RAZON[nombre]
        a, b = real.valores.get((r.categoria, r.clave)), sim.valores.get((r.categoria, r.clave))
        if a is None or b is None:
            continue
        if normalizar:
            if not a:
                continue
            v_real.append(100.0)
            v_sim.append(b / a * 100)
        else:
            v_real.append(a * escala(r))
            v_sim.append(b * escala(r))
        ejes.append(r.etiqueta)

    if len(ejes) < 3:
        st.info("Selecciona al menos 3 razones calculables.")
        return

    fig = go.Figure()
    for nombre, valores, color in (("Real (PDF)", v_real, COLOR_REAL), ("Simulado", v_sim, COLOR_SIM)):
        fig.add_trace(go.Scatterpolar(
            r=valores + [valores[0]], theta=ejes + [ejes[0]], name=nombre,
            fill="toself", opacity=0.55, line=dict(color=color),
        ))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True)), margin=dict(t=30, b=30, l=60, r=60))
    mostrar(fig, altura, key="radar")
    st.caption("Ojo: en razones donde menos es mejor (costos, apalancamiento), un valor mayor al de referencia es peor.")


# ── 3. Cascada técnica ───────────────────────────────────────────────────────
def _pasos_cascada(res: Resultado) -> list[float] | None:
    costos = [res.valores.get(r) for r in RUTAS_CASCADA]
    if any(c is None for c in costos):
        return None
    siniestralidad, adquisicion, operacion = costos
    return [100.0, -siniestralidad * 100, -adquisicion * 100, -operacion * 100,
            100.0 - (siniestralidad + adquisicion + operacion) * 100]


def tab_cascada(real: Resultado, sim: Resultado, altura: int) -> None:
    pasos = {"Real (PDF)": _pasos_cascada(real), "Simulado": _pasos_cascada(sim)}
    pasos = {k: v for k, v in pasos.items() if v}
    if not pasos:
        st.info("No hay costos medios calculables para construir la cascada.")
        return

    etiquetas = ["Prima", "− Siniestralidad", "− Adquisición", "− Operación", "Suficiencia"]
    fig = make_subplots(rows=1, cols=len(pasos), subplot_titles=list(pasos), shared_yaxes=True)
    for col, (_, y) in enumerate(pasos.items(), start=1):
        fig.add_trace(go.Waterfall(
            x=etiquetas, y=y, measure=["absolute", "relative", "relative", "relative", "total"],
            text=[f"{v:.2f}%" for v in y], textposition="outside",
            decreasing={"marker": {"color": "#DC2626"}},
            totals={"marker": {"color": COLOR_SIM}},
        ), row=1, col=col)
    fig.update_layout(showlegend=False, yaxis_title="% de la prima", margin=dict(t=50, b=10, l=10, r=10))
    mostrar(fig, altura, key="cascada")
    st.caption("Reproduce la lógica de analisis.py: Suficiencia = 100% − (siniestralidad + adquisición + operación). "
               "Cada costo medio usa su propio denominador, igual que el backend.")


# ── 4. Variaciones ───────────────────────────────────────────────────────────
def tab_variaciones(real: Resultado, sim: Resultado, altura: int) -> None:
    filas = []
    for r in CATALOGO:
        ruta = (r.categoria, r.clave)
        a, b = real.valores.get(ruta), sim.valores.get(ruta)
        if a is None or b is None or a == 0:
            continue
        if abs(b - a) < 1e-9:
            estado = "Sin cambio"
        elif r.mayor_mejor is None:
            estado = "Neutral"
        else:
            estado = "Mejora" if (b > a) == r.mayor_mejor else "Empeora"
        filas.append({"Razón": r.etiqueta, "Variación (%)": (b - a) / abs(a) * 100, "Estado": estado})

    df = pd.DataFrame(filas, columns=["Razón", "Variación (%)", "Estado"])
    solo_cambios = st.checkbox("Mostrar solo razones con cambio", value=True)
    if solo_cambios:
        df = df[df["Estado"] != "Sin cambio"]
    if df.empty:
        st.info("Modifica el simulador para ver el impacto porcentual sobre cada razón.")
        return

    df = df.sort_values("Variación (%)")
    fig = px.bar(
        df, x="Variación (%)", y="Razón", orientation="h", color="Estado", text_auto=".1f",
        color_discrete_map={"Mejora": "#16A34A", "Empeora": "#DC2626", "Neutral": COLOR_REAL,
                            "Sin cambio": "#D1D5DB"},
    )
    fig.update_layout(legend_title_text="", margin=dict(t=10, b=10, l=10, r=10))
    mostrar(fig, max(altura, 60 * len(df) + 120), key="variaciones")
    st.caption("Variación relativa del escenario simulado contra el real. Verde/rojo consideran si para esa razón "
               "es mejor un valor mayor o menor.")


# ── 5. Sensibilidad (tornado) ────────────────────────────────────────────────
def _indice_defecto() -> int:
    return list(OPCIONES_RAZON).index(etiqueta_razon(INDICE[("Suficiencia_Prima", "Suficiencia_Prima")]))


def tab_tornado(datos_real: dict, datos_sim: dict, altura: int) -> None:
    variables = variables_disponibles(datos_real)
    if not variables:
        st.info("No hay variables del simulador disponibles en el PDF.")
        return

    c1, c2 = st.columns([2, 1])
    nombre = c1.selectbox("Razón objetivo", list(OPCIONES_RAZON), index=_indice_defecto(), key="tornado_obj")
    variacion = c2.slider("Variación ±%", 1, 50, 10, key="tornado_pct")
    r = OPCIONES_RAZON[nombre]
    ruta = (r.categoria, r.clave)

    base = {k: a_numero(datos_sim.get(k)) for k in variables}
    valor_base = valor_objetivo(datos_real, base, ruta)
    if valor_base is None:
        st.warning("La razón objetivo no es calculable en el escenario actual.")
        return

    filas = []
    for clave, etiqueta in variables.items():
        if not base[clave]:
            continue
        efectos = []
        for signo in (-1, 1):
            entradas = dict(base)
            entradas[clave] = base[clave] * (1 + signo * variacion / 100)
            v = valor_objetivo(datos_real, entradas, ruta)
            efectos.append(None if v is None else (v - valor_base) * escala(r))
        if any(e is not None for e in efectos):
            filas.append((etiqueta, efectos[0], efectos[1]))
    if not filas:
        st.info("Ninguna variable altera esta razón en el rango elegido.")
        return

    filas.sort(key=lambda f: max(abs(f[1] or 0), abs(f[2] or 0)))  # mayor impacto arriba
    etiquetas = [f[0] for f in filas]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=etiquetas, x=[f[1] for f in filas], orientation="h",
                         name=f"−{variacion}%", marker_color="#F59E0B", opacity=0.85))
    fig.add_trace(go.Bar(y=etiquetas, x=[f[2] for f in filas], orientation="h",
                         name=f"+{variacion}%", marker_color=COLOR_SIM, opacity=0.85))
    fig.update_layout(barmode="overlay", legend_title_text="", margin=dict(t=10, b=10, l=10, r=10),
                      xaxis_title=f"Cambio en «{r.etiqueta}» ({'puntos porcentuales' if r.formato == 'pct' else 'veces'})")
    mostrar(fig, altura, key="tornado")
    st.caption(f"Valor base (escenario actual): {fmt_valor(valor_base, r.formato)}. "
               "Cada barra mueve una variable a la vez, manteniendo las demás.")


# ── 6. Mapa de calor 2D ──────────────────────────────────────────────────────
def tab_mapa2d(datos_real: dict, datos_sim: dict, altura: int) -> None:
    variables = variables_disponibles(datos_real)
    if len(variables) < 2:
        st.info("Se necesitan al menos 2 variables del simulador disponibles en el PDF.")
        return

    claves = list(variables)
    c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
    vx = c1.selectbox("Eje X", claves, index=0, format_func=variables.get, key="m2d_x")
    vy = c2.selectbox("Eje Y", claves, index=1, format_func=variables.get, key="m2d_y")
    nombre = c3.selectbox("Razón objetivo", list(OPCIONES_RAZON), index=_indice_defecto(), key="m2d_obj")
    rango = c4.slider("Rango ±%", 5, 50, 20, step=5, key="m2d_rango")
    if vx == vy:
        st.warning("Elige dos variables distintas.")
        return

    r = OPCIONES_RAZON[nombre]
    ruta = (r.categoria, r.clave)
    pasos = np.linspace(-rango, rango, 7)
    base = {k: a_numero(datos_sim.get(k)) for k in variables}

    z = np.full((len(pasos), len(pasos)), np.nan)
    for i, dy in enumerate(pasos):
        for j, dx in enumerate(pasos):
            entradas = dict(base)
            entradas[vx] = base[vx] * (1 + dx / 100)
            entradas[vy] = base[vy] * (1 + dy / 100)
            v = valor_objetivo(datos_real, entradas, ruta)
            if v is not None:
                z[i, j] = v * escala(r)
    if np.isnan(z).all():
        st.warning("La razón objetivo no es calculable en este rango.")
        return

    if r.mayor_mejor is True:
        paleta = "RdYlGn"
    elif r.mayor_mejor is False:
        paleta = "RdYlGn_r"
    else:
        paleta = "Blues"
    etiquetas = [f"{p:+.0f}%" for p in pasos]
    fig = px.imshow(
        z, x=etiquetas, y=etiquetas, text_auto=".2f", aspect="auto", origin="lower",
        color_continuous_scale=paleta,
        labels=dict(x=f"{variables[vx]} (variación)", y=f"{variables[vy]} (variación)",
                    color=f"{r.etiqueta} ({unidad(r)})"),
    )
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
    mostrar(fig, altura, key="mapa2d")
    st.caption("El centro (+0%, +0%) es el escenario actual del simulador. "
               "Verde = mejor, rojo = peor según la naturaleza de la razón.")


def render_explorador(datos_real: dict, datos_sim: dict, real: Resultado, sim: Resultado) -> None:
    st.subheader("🔬 Explorador avanzado")
    st.caption("Construye tus propias vistas y analiza el comportamiento de las razones con más herramientas. "
               "Cada gráfica incluye la barra de Plotly para hacer zoom, filtrar series o descargar PNG.")
    altura = st.session_state.get("altura_explorador", 450)

    tabs = st.tabs(["🎛️ Constructor libre", "📡 Radar", "🪜 Cascada técnica",
                    "📉 Variaciones", "🌪️ Sensibilidad", "🔥 Mapa de calor 2D"])
    with tabs[0]:
        tab_constructor(datos_real, datos_sim, real, sim, altura)
    with tabs[1]:
        tab_radar(real, sim, altura)
    with tabs[2]:
        tab_cascada(real, sim, altura)
    with tabs[3]:
        tab_variaciones(real, sim, altura)
    with tabs[4]:
        tab_tornado(datos_real, datos_sim, altura)
    with tabs[5]:
        tab_mapa2d(datos_real, datos_sim, altura)


# ─────────────────────────────────────────────────────────────────────────────
# EXPORTACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def render_descargas(datos_real: dict, datos_sim: dict, real: Resultado, sim: Resultado) -> None:
    filas_r = [
        {"Categoría": NOMBRES_CATEGORIA[r.categoria], "Razón": r.etiqueta,
         "Real": real.valores.get((r.categoria, r.clave)),
         "Simulado": sim.valores.get((r.categoria, r.clave))}
        for r in CATALOGO
    ]
    filas_c = [{"Cuenta": k, "Real": a_numero(v), "Simulado": a_numero(datos_sim.get(k))}
               for k, v in datos_real.items()]

    st.subheader("⬇️ Exportar")
    c1, c2 = st.columns(2)
    c1.download_button("Razones financieras (CSV)",
                       pd.DataFrame(filas_r).to_csv(index=False).encode("utf-8-sig"),
                       "razones_financieras.csv", "text/csv", use_container_width=True)
    c2.download_button("Cuentas extraídas (CSV)",
                       pd.DataFrame(filas_c).to_csv(index=False).encode("utf-8-sig"),
                       "cuentas_extraidas.csv", "text/csv", use_container_width=True)
    st.caption("Los porcentajes se exportan como fracción (0.15 = 15%).")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("📊 Análisis Financiero para Aseguradoras")
    st.caption("Sube un estado financiero en PDF, simula escenarios y revisa el impacto en tiempo real.")

    datos_real, datos_sim = render_sidebar()
    if datos_real is None or datos_sim is None:
        st.info("👈 Comienza subiendo un PDF en la barra lateral.")
        return

    try:
        real = analizar(datos_real)
        sim = analizar(datos_sim)
    except Exception as exc:  # noqa: BLE001
        st.error(
            f"Error al calcular las razones financieras: {exc}. "
            "Suele ocurrir cuando el extractor no encontró cuentas clave "
            "(utilidad neta, prima directa o capital contable). Revisa la pestaña de cuentas extraídas."
        )
        with st.expander("Cuentas extraídas del PDF"):
            st.json({k: a_numero(v) for k, v in datos_real.items()})
        st.stop()

    if datos_sim != datos_real:
        st.markdown("🔵 **Mostrando escenario simulado** — los deltas comparan contra los datos reales del PDF.")
    else:
        st.markdown("⚪ Sin cambios en el simulador: se muestran los datos reales del PDF.")

    render_kpis(real, sim, datos_real, datos_sim)
    st.divider()
    render_graficas(datos_sim, real, sim)
    st.divider()
    render_explorador(datos_real, datos_sim, real, sim)
    st.divider()
    render_insights(real, sim)
    render_detalle(datos_real, datos_sim, real, sim)
    st.divider()
    render_descargas(datos_real, datos_sim, real, sim)


if __name__ == "__main__":
    main()