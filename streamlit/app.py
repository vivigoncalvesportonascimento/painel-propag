import streamlit as st  # Biblioteca para criar o site
import pandas as pd     # Biblioteca para ler os dados processados
from pathlib import Path # Biblioteca para achar os arquivos nas pastas

# --- AJUSTE DE CAMINHOS ---
# O comando .parents[1] sobe 1 pasta para chegar na raiz.
# Estrutura: painel-propag/ -> streamlit/ -> app.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "processed_data"

# Configuração da aba do navegador (Título e Ícone)
st.set_page_config(page_title="Painel Propag 2026", layout="wide", page_icon="📊")

# Função com Cache: Carrega os dados uma vez e guarda na memória para ser rápido
@st.cache_data
def carregar_dados():
    try:
        # Lê os CSVs gerados pelo ETL usando o caminho absoluto
        df_g = pd.read_csv(DATA_PATH / "tabela_visao_geral.csv")
        df_i = pd.read_csv(DATA_PATH / "tabela_intervencoes.csv")
        return df_g, df_i
    except FileNotFoundError:
        return None, None

# Executa a função de carga
df_geral, df_int = carregar_dados()

# Se não achou os arquivos, para tudo e avisa o usuário
if df_geral is None:
    st.error(f"⚠️ Dados não encontrados na pasta: {DATA_PATH}. \n\nPor favor, execute o script 'etl.py' primeiro.")
    st.stop()

# ==============================================================================
# BARRA LATERAL (SIDEBAR) - FILTROS
# ==============================================================================
st.sidebar.header("Filtros")

# Cria lista de UOs disponíveis (ordem alfabética)
lista_uos = sorted(df_geral['uo_sigla'].dropna().astype(str).unique())

# Cria o seletor de UO
filtro_uo = st.sidebar.multiselect("Selecione a UO:", lista_uos)

# Função para aplicar o filtro selecionado nas tabelas
def filtrar(df):
    df_filtrado = df.copy()
    # Se o usuário selecionou alguma UO, filtra. Se não, mostra tudo.
    if filtro_uo: 
        df_filtrado = df_filtrado[df_filtrado['uo_sigla'].isin(filtro_uo)]
    return df_filtrado

# Cria as versões filtradas dos dados
df_g_show = filtrar(df_geral)
df_i_show = filtrar(df_int)

# ==============================================================================
# ÁREA PRINCIPAL - ABAS
# ==============================================================================
aba1, aba2 = st.tabs(["🏠 Visão Geral", "🏗️ Intervenções"])

# --- ABA 1: VISÃO GERAL ---
with aba1:
    st.title("Visão Geral: Limites vs Execução")
    
    # Cria 3 colunas para os Cartões de Métricas (KPIs)
    c1, c2, c3 = st.columns(3)
    
    # Calcula os totais baseados nos filtros
    c1.metric("Limite Total", f"R$ {df_g_show['valor_limite'].sum():,.2f}")
    c2.metric("Liquidado (Ex+RP)", f"R$ {df_g_show['vlr_liquidado_total'].sum():,.2f}")
    c3.metric("Saldo Disponível", f"R$ {df_g_show['saldo_limite'].sum():,.2f}")
    
    st.markdown("---") # Linha divisória
    
    # Exibe a tabela detalhada
    cols_ver = ['ano', 'uo_sigla', 'fonte_cod', 'valor_limite', 'vlr_liquidado_total', 'saldo_limite']
    
    st.dataframe(
        df_g_show[cols_ver].style.format("R$ {:,.2f}", subset=['valor_limite', 'vlr_liquidado_total', 'saldo_limite']),
        use_container_width=True, # Ocupa a largura total
        hide_index=True # Esconde a coluna de índice (0, 1, 2...)
    )

# --- ABA 2: INTERVENÇÕES ---
with aba2:
    st.title("Monitoramento por Intervenção")
    st.info("ℹ️ Dados filtrados pelas regras de negócio (Obras mapeadas).")
    
    # Métricas da aba
    c1, c2 = st.columns(2)
    c1.metric("Total Planejado", f"R$ {df_i_show['valor_plano'].sum():,.2f}")
    c2.metric("Total Executado", f"R$ {df_i_show['liquidado_final'].sum():,.2f}")

    # Função para pintar de vermelho se o saldo for negativo
    def cor_saldo(val): 
        return f'color: {"red" if val < 0 else "black"}'
    
    # Seleciona colunas para mostrar
    cols_int = ['cod_intervencao', 'intervencao', 'uo_sigla', 'valor_plano', 'liquidado_final', 'saldo_plano']
    
    # Exibe tabela com formatação
    st.dataframe(
        df_i_show[cols_int].style.format("R$ {:,.2f}", subset=['valor_plano', 'liquidado_final', 'saldo_plano'])
        .map(cor_saldo, subset=['saldo_plano']),
        use_container_width=True,
        hide_index=True
    )