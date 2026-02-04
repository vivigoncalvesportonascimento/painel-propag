# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from pathlib import Path
from io import StringIO

# ---------------------------------------------------------------------
# Configuração da página e CSS Personalizado
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Painel Propag 2026",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS para compactar a visualização e ajustar fontes
st.markdown("""
    <style>
        /* Reduzir padding do topo para ganhar espaço */
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
        /* Diminuir fonte das métricas */
        div[data-testid="stMetricValue"] {
            font-size: 1.1rem !important;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.8rem !important;
        }
        /* Ajustar fonte da tabela e outros textos */
        .stDataFrame, p, .stMultiSelect {
            font-size: 0.85rem;
        }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------


def format_brl(x: float) -> str:
    """Formata número como moeda pt-BR para exibição em Métricas (strings)."""
    try:
        s = f"{float(x):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Converte DataFrame para CSV (UTF-8) em bytes para download."""
    buff = StringIO()
    # Ao baixar, queremos o formato numérico puro ou formatado?
    # Geralmente técnico prefere puro (ponto decimal), gestor prefere vírgula.
    # Mantendo puro para facilitar reuso em Excel/PowerBI.
    df.to_csv(buff, index=False, encoding="utf-8", sep=";")
    return buff.getvalue().encode("utf-8")


def color_saldo(val):
    """Lógica de cor para o Pandas Styler: Vermelho se negativo, Azul se positivo."""
    if pd.isna(val):
        return ""
    color = "#e63946" if val < 0 else "#2a9d8f"
    return f'color: {color}; font-weight: bold;'

# ---------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    p_parquet = Path("data-processed/tbl_limite_liquidado_2026.parquet")
    p_csv = Path("data-processed/tbl_limite_liquidado_2026.csv")

    if p_parquet.exists():
        df = pd.read_parquet(p_parquet)
    elif p_csv.exists():
        df = pd.read_csv(p_csv, encoding="utf-8")
    else:
        st.error("⚠️ Arquivo não encontrado. Rode o ETL primeiro.")
        st.stop()

    if "Fonte (desc)" in df.columns:
        df = df.drop(columns=["Fonte (desc)"])

    # Conversão segura de tipos
    for col in ["Ano", "UO cod", "Fonte", "IPU"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    cols_float = ["Limite Propag 2026", "Liquidado 2026", "Saldo de limite"]
    for col in cols_float:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Criar coluna de % Execução para barra de progresso (0 a 1)
    # Evitar divisão por zero
    df["% Exec"] = df.apply(
        lambda row: row["Liquidado 2026"] / row["Limite Propag 2026"]
        if row["Limite Propag 2026"] > 0 else 0.0, axis=1
    )

    return df


# ---------------------------------------------------------------------
# App Principal
# ---------------------------------------------------------------------
st.title("Propag Investimentos: Monitoramento de Limites")

# Botão de recarga discreto no canto
if st.button("🔄 Atualizar", help="Limpa o cache e recarrega os dados"):
    st.cache_data.clear()
    st.rerun()

df = load_data()

# -----------------------------
# 1. Painel de Filtros (Expansível para economizar espaço)
# -----------------------------
with st.expander("🔎 Filtros Avançados", expanded=True):
    flt_cols = st.columns(5)

    with flt_cols[0]:
        anos = sorted(df["Ano"].unique())
        idx_ano = anos.index(2026) if 2026 in anos else 0
        sel_ano = st.selectbox("Ano", options=anos, index=idx_ano)

    # Filtragem preliminar pelo Ano para otimizar as listas seguintes
    df_ano = df[df["Ano"] == sel_ano]

    with flt_cols[1]:
        uos = sorted(df_ano["UO cod"].unique())
        sel_uo_cod = st.multiselect("UO (Cód)", options=uos)

    with flt_cols[2]:
        uo_siglas = sorted(df_ano["UO sigla"].dropna().unique())
        sel_uo_sigla = st.multiselect("UO (Sigla)", options=uo_siglas)

    with flt_cols[3]:
        fontes = sorted(df_ano["Fonte"].unique())
        sel_fonte = st.multiselect("Fonte", options=fontes)

    with flt_cols[4]:
        ipus = sorted(df_ano["IPU"].unique())
        sel_ipu = st.multiselect("IPU", options=ipus)

# Aplicação dos filtros
df_f = df_ano.copy()
if sel_uo_cod:
    df_f = df_f[df_f["UO cod"].isin(sel_uo_cod)]
if sel_uo_sigla:
    df_f = df_f[df_f["UO sigla"].isin(sel_uo_sigla)]
if sel_fonte:
    df_f = df_f[df_f["Fonte"].isin(sel_fonte)]
if sel_ipu:
    df_f = df_f[df_f["IPU"].isin(sel_ipu)]

# -----------------------------
# 2. KPIs (Indicadores no Topo)
# -----------------------------
# Estilo de container para destacar os totais
kpi_cols = st.columns(4)

total_limite = df_f["Limite Propag 2026"].sum()
total_liquidado = df_f["Liquidado 2026"].sum()
total_saldo = df_f["Saldo de limite"].sum()
pct_global = (total_liquidado / total_limite) if total_limite > 0 else 0

with kpi_cols[0]:
    st.metric("Registros Filtrados", f"{len(df_f)}")
with kpi_cols[1]:
    st.metric("Limite Total", format_brl(total_limite))
with kpi_cols[2]:
    st.metric("Liquidado Total", format_brl(total_liquidado),
              delta=f"{pct_global:.1%} executado", delta_color="off")
with kpi_cols[3]:
    # Delta colorido invertido (se saldo cair muito é ruim, mas aqui saldo positivo é normal)
    # Vamos usar cor normal. Se negativo, o próprio texto indicará.
    st.metric("Saldo Disponível", format_brl(total_saldo),
              delta_color="normal")

st.divider()

# -----------------------------
# 3. Tabela de Dados (Dataframe)
# -----------------------------

# Configuração de colunas para o st.dataframe
column_cfg = {
    "Ano": st.column_config.NumberColumn("Ano", format="%d", width="small"),
    "UO cod": st.column_config.NumberColumn("UO", format="%d", width="small"),
    "UO sigla": st.column_config.TextColumn("Sigla", width="small"),
    "Fonte": st.column_config.NumberColumn("Fonte", format="%d", width="small"),
    "IPU": st.column_config.NumberColumn("IPU", format="%d", width="small"),
    # Formatação nativa de moeda (pt-BR requer workaround ou string,
    # mas o format do streamlit "R$ %.2f" ajuda na ordenação numérica)
    "Limite Propag 2026": st.column_config.NumberColumn(
        "Limite", format="R$ %.2f", width="medium"
    ),
    "Liquidado 2026": st.column_config.NumberColumn(
        "Liquidado", format="R$ %.2f", width="medium"
    ),
    "Saldo de limite": st.column_config.NumberColumn(
        "Saldo", format="R$ %.2f", width="medium"
    ),
    "% Exec": st.column_config.ProgressColumn(
        "Execução", min_value=0, max_value=1, format="%.1f%%"
    ),
}

# Aplicar estilo condicional (cores) usando Pandas Styler
# Nota: formatamos o dataframe para visualização, mas mantemos os dados numéricos por baixo
styler = df_f.style.format({
    "Limite Propag 2026": "R$ {:,.2f}",
    "Liquidado 2026": "R$ {:,.2f}",
    "Saldo de limite": "R$ {:,.2f}",
    "% Exec": "{:.1%}"
}, thousands=".", decimal=",").applymap(color_saldo, subset=["Saldo de limite"])

st.dataframe(
    styler,
    column_config=column_cfg,
    use_container_width=True,
    hide_index=True,
    height=500  # Altura fixa para evitar scroll infinito da página inteira
)

# -----------------------------
# Download
# -----------------------------
st.download_button(
    label="⬇️ Baixar Dados Filtrados (.csv)",
    data=to_csv_bytes(df_f),
    file_name="monitoramento_propag_2026.csv",
    mime="text/csv",
    help="Baixa a tabela exibida acima em formato CSV separado por ponto-e-vírgula"
)
