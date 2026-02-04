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


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Converte DataFrame para CSV (UTF-8) em bytes para download."""
    buff = StringIO()
    df.to_csv(buff, index=False, encoding="utf-8")
    return buff.getvalue().encode("utf-8")


def to_int64_safe(series: pd.Series) -> pd.Series:
    """
    Converte para inteiro nulo-tolerante (Int64) sem usar errors='ignore'.
    Se a conversão não fizer sentido, retorna série original.
    """
    s = pd.to_numeric(series, errors="coerce")
    # Se quase tudo vira NaN, mantenha original (evita quebrar colunas textuais por engano)
    if s.notna().sum() == 0:
        return series
    return s.astype("Int64")


def to_float_safe(series: pd.Series) -> pd.Series:
    """Converte para float com coerce + fillna."""
    return pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)

# ---------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    """
    Carrega a tabela final do ETL (preferência Parquet, fallback CSV).
    Remove 'Fonte (desc)' se existir e garante tipos.
    """
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

    # Remover 'Fonte (desc)' se existir
    if "Fonte (desc)" in df.columns:
        df = df.drop(columns=["Fonte (desc)"])

    # Seleção/ordem de colunas esperadas
    cols = [
        "Ano", "UO cod", "UO sigla", "Fonte",
        "IPU", "Limite Propag 2026", "Liquidado 2026", "Saldo de limite",
    ]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        st.error("Colunas esperadas não encontradas: " + ", ".join(missing))
        st.stop()

    # Tipos (sem errors='ignore')
    df["Ano"] = to_int64_safe(df["Ano"])
    df["UO cod"] = to_int64_safe(df["UO cod"])
    df["Fonte"] = to_int64_safe(df["Fonte"])
    df["IPU"] = to_int64_safe(df["IPU"])

    for m in ["Limite Propag 2026", "Liquidado 2026", "Saldo de limite"]:
        df[m] = to_float_safe(df[m])

    return df[cols].copy()


# ---------------------------------------------------------------------
# App
# ---------------------------------------------------------------------
st.markdown("### Progag Investimentos - Limite vs Liquidado")


# Botão para recarregar os dados (limpa cache)
cols_header = st.columns([1, 5])
with cols_header[0]:
    if st.button("🔄 Recarregar dados"):
        st.cache_data.clear()

df = load_data()

# -----------------------------
# Filtros
# -----------------------------
flt_cols = st.columns(5)

with flt_cols[0]:
    anos = sorted(
        [a for a in df["Ano"].dropna().unique().tolist() if pd.notna(a)])
    # Se houver 2026, selecione-o por padrão; senão, primeiro da lista
    default_idx = anos.index(2026) if 2026 in anos else 0
    sel_ano = st.selectbox("Ano", options=anos,
                           index=default_idx if anos else 0)

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

# Substitui use_container_width=True -> width="stretch"
st.dataframe(
    df_show,
    width="stretch",
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
