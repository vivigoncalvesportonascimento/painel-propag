# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from pathlib import Path
from io import StringIO

# =============================================================================
# Configuração da página
# =============================================================================
st.set_page_config(
    page_title="Painel Propag 2026",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =============================================================================
# Paths robustos (permite rodar da raiz ou de /streamlit)
# =============================================================================
# .../painel-propag/streamlit/app.py -> parents[1] = .../painel-propag
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data-processed"

# =============================================================================
# Utilitários
# =============================================================================


def format_brl(x: float) -> str:
    """Formata número como moeda pt-BR para exibição."""
    try:
        s = f"{float(x):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Converte DataFrame para CSV (UTF-8) em bytes para download."""
    buff = StringIO()
    df.to_csv(buff, index=False, encoding="utf-8", sep=";")
    return buff.getvalue().encode("utf-8")


def color_saldo(val):
    """Styler.map: vermelho se negativo, azul se positivo."""
    if pd.isna(val):
        return ""
    color = "#e63946" if val < 0 else "#2a9d8f"
    return f'color: {color}; font-weight: bold;'


def filter_with_multiselects(df: pd.DataFrame, selections: dict) -> pd.DataFrame:
    """
    Aplica filtros de multiselect de forma segura:
      - inicia máscara booleana com True para todas as linhas
      - aplica .isin(valores) somente quando a lista não está vazia
    selections: { "coluna_no_df": [valores_selecionados], ... }
    """
    if df.empty:
        return df.copy()
    mask = pd.Series(True, index=df.index)
    for col, vals in selections.items():
        if col in df.columns and vals:  # só filtra se houver seleção
            mask = mask & df[col].isin(vals)
    return df[mask].copy()

# =============================================================================
# Loaders (com cache)
# =============================================================================


@st.cache_data(show_spinner=False)
def load_tbl1() -> pd.DataFrame:
    """
    Tabela 1 — Visão Geral
    Espera: data-processed/tbl_limite_liquidado_2026.(parquet|csv)
    """
    p_parquet = DATA_DIR / "tbl_limite_liquidado_2026.parquet"
    p_csv = DATA_DIR / "tbl_limite_liquidado_2026.csv"

    if p_parquet.exists():
        df = pd.read_parquet(p_parquet)
    elif p_csv.exists():
        df = pd.read_csv(p_csv, encoding="utf-8")
    else:
        st.error("⚠️ Arquivo da Tabela 1 não encontrado. Rode o ETL primeiro.")
        st.stop()

    # Ajustes de colunas/tipos (mantendo o contrato atual da Tabela 1)
    if "Fonte (desc)" in df.columns:
        df = df.drop(columns=["Fonte (desc)"])
    for col in ["Ano", "UO cod", "Fonte", "IPU"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col], errors="coerce").fillna(0).astype(int)
    for col in ["Limite Propag 2026", "Liquidado 2026", "Saldo de limite"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # % Execução
    if all(c in df.columns for c in ["Limite Propag 2026", "Liquidado 2026"]):
        df["% Exec"] = df.apply(
            lambda r: (r["Liquidado 2026"] / r["Limite Propag 2026"]
                       ) if r["Limite Propag 2026"] > 0 else 0.0,
            axis=1
        )
    return df


@st.cache_data(show_spinner=False)
def load_tbl2() -> pd.DataFrame:
    """
    Tabela 2 — Crédito, Cota, Execução e RP
    Espera: data-processed/tbl_pagina1_tabela2_2026.csv
    """
    p = DATA_DIR / "tbl_pagina1_tabela2_2026.csv"
    if not p.exists():
        st.error("⚠️ Tabela 2 não encontrada. Rode: poetry run build-tbl-pg1-tb2")
        st.stop()
    df = pd.read_csv(p, encoding="utf-8")

    for c in ["ano", "uo_cod", "acao_cod", "grupo_cod", "iag_cod", "fonte_cod", "ipu_cod"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ["limite_propag", "vlr_credito_inicial", "vlr_credito_autorizado", "vlr_cota_aprovada",
              "vlr_empenhado", "Liquidado_2026", "Pago_Orc_2026"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


@st.cache_data(show_spinner=False)
def load_intervencao() -> pd.DataFrame:
    """
    Página 2 — Detalhamento por Intervenção
    Espera: data-processed/tbl_pagina2_intervencao_2026.csv
    """
    p = DATA_DIR / "tbl_pagina2_intervencao_2026.csv"
    if not p.exists():
        st.error(
            "⚠️ Tabela de Intervenção não encontrada. Rode: poetry run build-pg2-intervencao")
        st.stop()
    df = pd.read_csv(p, encoding="utf-8")

    for c in ["ano", "uo_cod", "acao_cod", "intervencao_cod", "fonte_cod", "ipu_cod"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ["liquidado_2026", "limite_propag"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    df["saldo_limite"] = df["limite_propag"] - df["liquidado_2026"]
    return df


# =============================================================================
# App com abas
# =============================================================================
st.title("Propag Investimentos: Monitoramento de Limites")

tab1, tab2, tab3 = st.tabs([
    "Página 1 — Tabela 1 (Visão Geral)",
    "Página 1 — Tabela 2 (Crédito, Cota, Execução e RP)",
    "Página 2 — Detalhamento por Intervenção"
])

# -----------------------------------------------------------------------------
# TAB 1: Tabela 1 (Visão Geral)
# -----------------------------------------------------------------------------
with tab1:
    if st.button("🔄 Atualizar", help="Limpa o cache e recarrega os dados", key="refresh_tab1"):
        st.cache_data.clear()
        st.rerun()

    df = load_tbl1()

    # Filtros (chaves únicas para evitar IDs duplicados)
    with st.expander("🔎 Filtros Avançados", expanded=True):
        flt_cols = st.columns(5)
        with flt_cols[0]:
            anos = sorted(df["Ano"].unique())
            idx_ano = anos.index(2026) if 2026 in anos else 0
            sel_ano = st.selectbox("Ano", options=anos,
                                   index=idx_ano, key="t1_ano")
        df_ano = df[df["Ano"] == sel_ano]
        with flt_cols[1]:
            sel_uo_cod = st.multiselect("UO (Cód)", options=sorted(
                df_ano["UO cod"].unique()), key="t1_uo_cod")
        with flt_cols[2]:
            sel_uo_sigla = st.multiselect("UO (Sigla)", options=sorted(
                df_ano["UO sigla"].dropna().unique()), key="t1_uo_sigla")
        with flt_cols[3]:
            sel_fonte = st.multiselect("Fonte", options=sorted(
                df_ano["Fonte"].unique()), key="t1_fonte")
        with flt_cols[4]:
            sel_ipu = st.multiselect("IPU", options=sorted(
                df_ano["IPU"].unique()), key="t1_ipu")

        df_f = df_ano.copy()
        if sel_uo_cod:
            df_f = df_f[df_f["UO cod"].isin(sel_uo_cod)]
        if sel_uo_sigla:
            df_f = df_f[df_f["UO sigla"].isin(sel_uo_sigla)]
        if sel_fonte:
            df_f = df_f[df_f["Fonte"].isin(sel_fonte)]
        if sel_ipu:
            df_f = df_f[df_f["IPU"].isin(sel_ipu)]

    # KPIs
    kpi_cols = st.columns(4)
    total_limite = df_f["Limite Propag 2026"].sum()
    total_liquidado = df_f["Liquidado 2026"].sum()
    total_saldo = df_f["Saldo de limite"].sum()
    pct_global = (total_liquidado / total_limite) if total_limite > 0 else 0
    kpi_cols[0].metric("Registros Filtrados", f"{len(df_f)}")
    kpi_cols[1].metric("Limite Total", format_brl(total_limite))
    kpi_cols[2].metric("Liquidado Total", format_brl(
        total_liquidado), delta=f"{pct_global:.1%} executado", delta_color="off")
    kpi_cols[3].metric("Saldo Disponível", format_brl(total_saldo))

    st.divider()

    # Tabela (usa Styler.map e width='stretch')
    column_cfg = {
        "Ano":     st.column_config.NumberColumn("Ano", format="%d", width="small"),
        "UO cod":  st.column_config.NumberColumn("UO", format="%d", width="small"),
        "UO sigla": st.column_config.TextColumn("Sigla", width="small"),
        "Fonte":   st.column_config.NumberColumn("Fonte", format="%d", width="small"),
        "IPU":     st.column_config.NumberColumn("IPU", format="%d", width="small"),
        "Limite Propag 2026":  st.column_config.NumberColumn("Limite", format="R$ %.2f", width="medium"),
        "Liquidado 2026":      st.column_config.NumberColumn("Liquidado", format="R$ %.2f", width="medium"),
        "Saldo de limite":     st.column_config.NumberColumn("Saldo", format="R$ %.2f", width="medium"),
        "% Exec":              st.column_config.ProgressColumn("Execução", min_value=0, max_value=1, format="%.1f%%"),
    }

    styler = (
        df_f.style
        .format({
            "Limite Propag 2026": "R$ {:,.2f}",
            "Liquidado 2026": "R$ {:,.2f}",
            "Saldo de limite": "R$ {:,.2f}",
            "% Exec": "{:.1%}"
        }, thousands=".", decimal=",")
        .map(color_saldo, subset=["Saldo de limite"])
    )

    st.dataframe(
        styler,
        column_config=column_cfg,
        width="stretch",
        hide_index=True,
        height=500
    )

    st.download_button(
        label="⬇️ Baixar Dados Filtrados (.csv)",
        data=to_csv_bytes(df_f),
        file_name="monitoramento_propag_2026.csv",
        mime="text/csv"
    )

# -----------------------------------------------------------------------------
# TAB 2: Tabela 2 (Crédito, Cota, Execução e RP)
# -----------------------------------------------------------------------------
with tab2:
    st.subheader(
        "Crédito, Cota, Execução e RP — 2026 (Grão: ANO, UO, AÇÃO, GRUPO, IAG, FONTE, IPU)")
    if st.button("🔄 Atualizar", key="refresh_tab2"):
        st.cache_data.clear()
        st.rerun()

    df2 = load_tbl2()

    c1, c2, c3, c4 = st.columns(4)
    uo = c1.multiselect("UO",     sorted(
        df2["uo_cod"].unique()),     key="t2_uo")
    acao = c2.multiselect("Ação",   sorted(
        df2["acao_cod"].unique()),   key="t2_acao")
    fonte = c3.multiselect("Fonte",  sorted(
        df2["fonte_cod"].unique()),  key="t2_fonte")
    ipu = c4.multiselect("IPU",    sorted(
        df2["ipu_cod"].unique()),    key="t2_ipu")

    df2_f = filter_with_multiselects(
        df2,
        {
            "uo_cod": uo,
            "acao_cod": acao,
            "fonte_cod": fonte,
            "ipu_cod": ipu,
        }
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Limite",            format_brl(df2_f["limite_propag"].sum()))
    k2.metric("Empenhado",         format_brl(df2_f["vlr_empenhado"].sum()))
    k3.metric("Liquidado",         format_brl(df2_f["Liquidado_2026"].sum()))
    k4.metric("Pago Orçamentário", format_brl(df2_f["Pago_Orc_2026"].sum()))

    st.dataframe(
        df2_f.rename(columns={
            "limite_propag": "Limite Propag 2026",
            "vlr_credito_inicial": "Crédito Inicial 2026",
            "vlr_credito_autorizado": "Crédito Autorizado 2026",
            "vlr_cota_aprovada": "Cota Aprovada 2026",
            "vlr_empenhado": "Empenhado 2026"
        }),
        width="stretch",
        hide_index=True
    )

    st.download_button(
        "⬇️ Baixar (.csv)",
        data=to_csv_bytes(df2_f),
        file_name="pagina1_tabela2_2026.csv",
        mime="text/csv"
    )

# -----------------------------------------------------------------------------
# TAB 3: Detalhamento por Intervenção
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("Detalhamento por Intervenção — 2026")
    if st.button("🔄 Atualizar", key="refresh_tab3"):
        st.cache_data.clear()
        st.rerun()

    df3 = load_intervencao()

    c1, c2, c3, c4 = st.columns(4)
    uo = c1.multiselect("UO",     sorted(
        df3["uo_cod"].unique()),     key="t3_uo")
    acao = c2.multiselect("Ação",   sorted(
        df3["acao_cod"].unique()),   key="t3_acao")
    fonte = c3.multiselect("Fonte",  sorted(
        df3["fonte_cod"].unique()),  key="t3_fonte")
    ipu = c4.multiselect("IPU",    sorted(
        df3["ipu_cod"].unique()),    key="t3_ipu")

    dff = filter_with_multiselects(
        df3,
        {
            "uo_cod": uo,
            "acao_cod": acao,
            "fonte_cod": fonte,
            "ipu_cod": ipu,
        }
    )

    k1, k2, k3 = st.columns(3)
    k1.metric("Limite Intervenção",    format_brl(dff["limite_propag"].sum()))
    k2.metric("Liquidado Intervenção", format_brl(dff["liquidado_2026"].sum()))
    k3.metric("Saldo",                 format_brl(dff["saldo_limite"].sum()))

    st.dataframe(
        dff.rename(columns={
            "intervencao_cod": "Intervenção",
            "liquidado_2026": "Liquidado 2026",
            "limite_propag": "Limite Propag 2026",
            "saldo_limite": "Saldo de Limite"
        }),
        width="stretch",
        hide_index=True
    )

    st.download_button(
        "⬇️ Baixar (.csv)",
        data=to_csv_bytes(dff),
        file_name="pagina2_intervencao_2026.csv",
        mime="text/csv"
    )
