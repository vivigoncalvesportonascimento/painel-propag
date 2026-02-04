# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from pathlib import Path
from io import StringIO

# ---------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------
st.set_page_config(
    layout="wide",
)

# ---------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------


def format_brl(x: float) -> str:
    """Formata número como moeda pt-BR (R$ com vírgula decimal)."""
    try:
        s = f"{float(x):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    """Carrega a tabela final do ETL (preferência Parquet, fallback CSV)."""
    p_parquet = Path("data-processed/tbl_limite_liquidado_2026.parquet")
    p_csv = Path("data-processed/tbl_limite_liquidado_2026.csv")

    if p_parquet.exists():
        df = pd.read_parquet(p_parquet)
    elif p_csv.exists():
        df = pd.read_csv(p_csv, encoding="utf-8")
    else:
        st.error(
            "Arquivo processado não encontrado em **data-processed/**. "
            "Rode antes o ETL: `poetry run build-tbl-limite-liquidado`."
        )
        st.stop()

    # Remover 'Fonte (desc)' se existir, mantendo somente os campos desejados
    if "Fonte (desc)" in df.columns:
        df = df.drop(columns=["Fonte (desc)"])

    # Garantir a ordem/seleção de colunas
    cols = [
        "Ano", "UO cod", "UO sigla", "Fonte",
        "IPU", "Limite Propag 2026", "Liquidado 2026", "Saldo de limite",
    ]
    # Validação simples (para evitar KeyError caso haja variações)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.error(
            "Colunas esperadas não encontradas: "
            + ", ".join(missing)
            + ". Verifique o ETL e os nomes gerados."
        )
        st.stop()

    # Tipos
    for c in ["Ano", "UO cod", "Fonte", "IPU"]:
        df[c] = pd.to_numeric(df[c], errors="ignore")

    # As métricas devem ser numéricas
    for m in ["Limite Propag 2026", "Liquidado 2026", "Saldo de limite"]:
        df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0.0)

    # Reordenar e retornar
    return df[cols].copy()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Converte DataFrame para CSV (UTF-8) em bytes para download."""
    buff = StringIO()
    df.to_csv(buff, index=False, encoding="utf-8")
    return buff.getvalue().encode("utf-8")


# ---------------------------------------------------------------------
# App
# ---------------------------------------------------------------------
st.markdown("#### Propag - Limite vs Liquidado")


df = load_data()

# -----------------------------
# Filtros (multiselects + selectbox)
# -----------------------------
flt_cols = st.columns(5)

with flt_cols[0]:
    anos = sorted(df["Ano"].dropna().unique().tolist())
    sel_ano = st.selectbox("Ano", options=anos, index=0)

with flt_cols[1]:
    uos = sorted(df["UO cod"].dropna().unique().tolist())
    sel_uo_cod = st.multiselect("UO cod", options=uos, default=[])

with flt_cols[2]:
    uo_siglas = sorted(df["UO sigla"].dropna().unique().tolist())
    sel_uo_sigla = st.multiselect("UO sigla", options=uo_siglas, default=[])

with flt_cols[3]:
    fontes = sorted(df["Fonte"].dropna().unique().tolist())
    sel_fonte = st.multiselect("Fonte", options=fontes, default=[])

with flt_cols[4]:
    ipus = sorted(df["IPU"].dropna().unique().tolist())
    sel_ipu = st.multiselect("IPU", options=ipus, default=[])

# Aplicar filtros
df_f = df.query("Ano == @sel_ano").copy()
if sel_uo_cod:
    df_f = df_f[df_f["UO cod"].isin(sel_uo_cod)]
if sel_uo_sigla:
    df_f = df_f[df_f["UO sigla"].isin(sel_uo_sigla)]
if sel_fonte:
    df_f = df_f[df_f["Fonte"].isin(sel_fonte)]
if sel_ipu:
    df_f = df_f[df_f["IPU"].isin(sel_ipu)]

# -----------------------------
# Tabela (formatada em pt-BR)
# -----------------------------
df_show = df_f.copy()
for c in ["Limite Propag 2026", "Liquidado 2026", "Saldo de limite"]:
    df_show[c] = df_show[c].apply(format_brl)

st.dataframe(
    df_show,
    use_container_width=True,
    hide_index=True,
)

# -----------------------------
# Resumo e download
# -----------------------------
col_a, col_b, col_c, col_d = st.columns([1, 1, 1, 2])

with col_a:
    st.metric("Registros", f"{len(df_f):,}".replace(",", "."))
with col_b:
    st.metric("Limite Propag 2026", format_brl(
        df_f["Limite Propag 2026"].sum()))
with col_c:
    st.metric("Liquidado 2026", format_brl(df_f["Liquidado 2026"].sum()))
with col_d:
    st.metric("Saldo de limite", format_brl(df_f["Saldo de limite"].sum()))

st.download_button(
    label="⬇️ Baixar recorte (CSV)",
    data=to_csv_bytes(df_f),
    file_name="tbl_limite_liquidado_2026_filtrado.csv",
    mime="text/csv",
)
