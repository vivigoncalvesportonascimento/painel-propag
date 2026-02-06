import streamlit as st
import pandas as pd

# Configuração da Página do Navegador
st.set_page_config(page_title="Painel Propag 2026", layout="wide", page_icon="📊")

# ==============================================================================
# CARREGAMENTO DOS DADOS
# ==============================================================================
@st.cache_data
def carregar_dados():
    try:
        # Lê os CSVs gerados pelo etl.py
        df_g = pd.read_csv("processed_data/tabela_visao_geral.csv")
        df_i = pd.read_csv("processed_data/tabela_intervencoes.csv")
        return df_g, df_i
    except FileNotFoundError:
        return None, None

df_geral, df_int = carregar_dados()

# Verifica se os dados existem
if df_geral is None:
    st.error("⚠️ Dados não encontrados! Por favor, execute o script 'etl.py' primeiro.")
    st.stop()

# ==============================================================================
# BARRA LATERAL (FILTROS)
# ==============================================================================
st.sidebar.header("Filtros")

# Filtro de UO
lista_uos = sorted(df_geral['uo_sigla'].dropna().astype(str).unique())
filtro_uo = st.sidebar.multiselect("Selecione a UO:", lista_uos)

# Função para aplicar filtros nos dados
def filtrar(df):
    df_filtrado = df.copy()
    if filtro_uo:
        df_filtrado = df_filtrado[df_filtrado['uo_sigla'].isin(filtro_uo)]
    return df_filtrado

df_g_show = filtrar(df_geral)
df_i_show = filtrar(df_int)

# ==============================================================================
# INTERFACE PRINCIPAL (ABAS)
# ==============================================================================
aba1, aba2 = st.tabs(["🏠 Visão Geral", "🏗️ Intervenções"])

# --- ABA 1: VISÃO GERAL ---
with aba1:
    st.title("Visão Geral: Limites vs Execução")
    
    # Cartões de Métricas (KPIs)
    col1, col2, col3 = st.columns(3)
    
    val_limite = df_g_show['valor_limite'].sum()
    val_exec = df_g_show['vlr_liquidado_total'].sum()
    val_saldo = df_g_show['saldo_limite'].sum()
    
    col1.metric("Limite Total", f"R$ {val_limite:,.2f}")
    col2.metric("Liquidado (Ex + RP)", f"R$ {val_exec:,.2f}")
    col3.metric("Saldo Disponível", f"R$ {val_saldo:,.2f}")
    
    st.markdown("---")
    
    st.subheader("Detalhamento por UO e Fonte")
    
    # Seleção de colunas para exibir
    cols_visiveis = ['ano', 'uo_sigla', 'fonte_cod', 'valor_limite', 'vlr_liquidado_total', 'saldo_limite']
    
    st.dataframe(
        df_g_show[cols_visiveis].rename(columns={
            'uo_sigla': 'Unidade Orçamentária',
            'fonte_cod': 'Fonte',
            'valor_limite': 'Limite',
            'vlr_liquidado_total': 'Liquidado Total',
            'saldo_limite': 'Saldo'
        }).style.format({
            'Limite': 'R$ {:,.2f}',
            'Liquidado Total': 'R$ {:,.2f}',
            'Saldo': 'R$ {:,.2f}'
        }),
        use_container_width=True,
        hide_index=True
    )

# --- ABA 2: INTERVENÇÕES ---
with aba2:
    st.title("Monitoramento por Intervenção")
    st.info("ℹ️ Exibindo dados conforme regras específicas de mapeamento de obras.")
    
    # KPIs da Aba
    total_plano = df_i_show['valor_plano'].sum()
    total_real = df_i_show['liquidado_final'].sum()
    
    k1, k2 = st.columns(2)
    k1.metric("Total Planejado (Intervenções)", f"R$ {total_plano:,.2f}")
    k2.metric("Total Executado", f"R$ {total_real:,.2f}")
    
    st.markdown("---")
    
    # Tabela Principal
    # Filtra colunas relevantes
    cols_int = ['cod_intervencao', 'intervencao', 'uo_sigla', 'valor_plano', 'liquidado_final', 'saldo_plano']
    
    # Formatação condicional para Saldo Negativo (Vermelho)
    def cor_saldo(val):
        color = 'red' if val < 0 else 'black'
        return f'color: {color}'
    
    st.dataframe(
        df_i_show[cols_int].rename(columns={
            'cod_intervencao': 'Cód.',
            'intervencao': 'Descrição da Intervenção',
            'uo_sigla': 'UO',
            'valor_plano': 'Limite Planejado',
            'liquidado_final': 'Liquidado Real',
            'saldo_plano': 'Saldo'
        }).style.format({
            'Limite Planejado': 'R$ {:,.2f}',
            'Liquidado Real': 'R$ {:,.2f}',
            'Saldo': 'R$ {:,.2f}'
        }).map(cor_saldo, subset=['Saldo']),
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("*Nota: Linhas com 'SEM_REF' ou vazias indicam execução sem intervenção mapeada na planilha de limites.*")