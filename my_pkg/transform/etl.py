import pandas as pd  # Biblioteca principal para manipular tabelas de dados
import numpy as np   # Biblioteca para cálculos matemáticos avançados
import os            # Biblioteca para comandos do sistema operacional (criar pastas)
import warnings      # Biblioteca para controlar avisos de erro
from pathlib import Path # Biblioteca moderna para lidar com caminhos de arquivos de forma inteligente

# ==============================================================================
# CONFIGURAÇÕES INICIAIS
# ==============================================================================
# Ignora avisos de "warnings" para não poluir o terminal com mensagens amarelas desnecessárias
warnings.filterwarnings('ignore')

print(">>> INICIANDO O PROCESSAMENTO DE DADOS (ETL) - COM COMENTÁRIOS <<<")

# --- AJUSTE DE CAMINHOS (O "PULO DO GATO") ---
# Este comando descobre onde este arquivo (etl.py) está e "volta" duas pastas para achar a raiz.
# Estrutura: painel-propag/ (Raiz) -> my_pkg/ -> transform/ -> etl.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]

print(f"   [INFO] A raiz do projeto foi identificada em: {PROJECT_ROOT}")

# Definimos os caminhos completos baseados na raiz encontrada acima
PATH_RAW = PROJECT_ROOT / "data-raw"
PATH_AUX = PROJECT_ROOT / "datapackages/aux-classificadores/data"
PATH_SIAFI = PROJECT_ROOT / "datapackages/siafi-2026/data"
PATH_OUT = PROJECT_ROOT / "processed_data"

# Cria a pasta de saída (processed_data) se ela ainda não existir
os.makedirs(PATH_OUT, exist_ok=True)

# ==============================================================================
# 1. FUNÇÃO DE LEITURA INTELIGENTE
# ==============================================================================
def ler_csv_seguro(path, encoding='utf-8', compression=None):
    """
    Função robusta que tenta ler o arquivo CSV.
    Ela resolve dois problemas comuns:
    1. Códigos que começam com zero (ex: '0100') virando número (100).
    2. Arquivos salvos com ponto-e-vírgula (Brasil) ou vírgula (EUA).
    """
    # Lista de colunas que OBRIGATORIAMENTE devem ser lidas como Texto (String)
    # Isso impede que o Excel/Pandas suma com os zeros à esquerda.
    cols_str = {
        'uo_cod': str, 'acao_cod': str, 'fonte_cod': str, 'ipu_cod': str, 
        'grupo_cod': str, 'iag_cod': str, 'elemento_item_cod': str, 
        'intervencao_cod': str, 'num_obra': str, 
        'funcao_cod': str, 'programa_cod': str
    }
    
    # Tentaremos ler primeiro com ponto e vírgula, depois com vírgula
    separadores = [';', ',']
    
    # Converte o caminho do arquivo para texto (o pandas precisa disso)
    path_str = str(path)
    
    for sep in separadores:
        try:
            # Tenta ler o arquivo com as configurações atuais
            df = pd.read_csv(path_str, encoding=encoding, sep=sep, compression=compression, dtype=cols_str)
            
            # Verificação: Se o arquivo tiver só 1 coluna, provavelmente o separador está errado
            if df.shape[1] <= 1 and sep == ';': 
                continue # Pula para a próxima tentativa (vírgula)
            
            # Limpeza 1: Padroniza os nomes das colunas (tudo minúsculo, sem espaços nas pontas)
            df.columns = [c.strip().lower() for c in df.columns]
            
            # Limpeza 2: Remove espaços em branco dentro das células de texto
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].str.strip()
            
            print(f"   [OK] Lido com sucesso: {path.name} ({len(df)} linhas)")
            return df # Retorna a tabela carregada
            
        except Exception:
            continue # Se der erro, tenta o próximo separador

    # Se falhar todas as tentativas, avisa e retorna uma tabela vazia
    print(f"   [ERRO CRÍTICO] Não foi possível ler o arquivo: {path.name}")
    return pd.DataFrame()

# ==============================================================================
# 2. CARREGAMENTO DOS DADOS (LOAD)
# ==============================================================================
print("1/5 - Carregando arquivos do disco...")

# Carrega tabelas auxiliares (Dimensões)
df_uo = ler_csv_seguro(PATH_AUX / "uo.csv")
df_acao = ler_csv_seguro(PATH_AUX / "acao.csv")

# --- CARREGA E TRATA A TABELA DE LIMITES ---
df_limites = ler_csv_seguro(PATH_RAW / "propag_investimentos_limite_2026.csv", encoding='utf-8') 

# Renomeia a coluna 'limite_propag' (do seu YAML) para 'valor_limite' (padrão do script)
if 'limite_propag' in df_limites.columns:
    df_limites.rename(columns={'limite_propag': 'valor_limite'}, inplace=True)

# Converte o valor para número (caso venha como texto "1.000,00")
if not df_limites.empty and 'valor_limite' in df_limites.columns:
    if df_limites['valor_limite'].dtype == 'O': # 'O' significa Object (Texto)
        df_limites['valor_limite'] = df_limites['valor_limite'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    df_limites['valor_limite'] = pd.to_numeric(df_limites['valor_limite'], errors='coerce').fillna(0)

# --- CARREGA E TRATA A TABELA DE INTERVENÇÕES ---
# Usa encoding cp1252 pois geralmente vem de Excel manual
df_intervencoes = ler_csv_seguro(PATH_RAW / "propag_investimentos_intervencoes_plano_2026.csv", encoding='cp1252')

# Garante que temos a coluna de valor
if not df_intervencoes.empty and 'valor_plano' in df_intervencoes.columns:
    if df_intervencoes['valor_plano'].dtype == 'O':
        df_intervencoes['valor_plano'] = df_intervencoes['valor_plano'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    df_intervencoes['valor_plano'] = pd.to_numeric(df_intervencoes['valor_plano'], errors='coerce').fillna(0)
else:
    # Se não achar a coluna, cria ela com zeros para não travar o painel
    df_intervencoes['valor_plano'] = 0.0

# --- CARREGA TABELAS DO SIAFI (EXECUÇÃO) ---
# Usa compression='gzip' porque os arquivos terminam em .gz
df_execucao = ler_csv_seguro(PATH_SIAFI / "execucao.csv.gz", compression='gzip')
df_rp = ler_csv_seguro(PATH_SIAFI / "restos_pagar.csv.gz", compression='gzip')

# ==============================================================================
# 3. FILTROS GLOBAIS (TRANSFORM)
# ==============================================================================
print("2/5 - Aplicando filtros de negócio (IPU=0 ou Fonte=89)...")

def filtrar_propag(df):
    """Função que aplica a regra: Só quero dados onde IPU é 0 OU Fonte é 89"""
    if df.empty: return df
    
    # Cria uma lista de Verdadeiro/Falso inicialmente toda Falsa
    condicao = pd.Series(False, index=df.index)
    
    # Se tiver coluna IPU, marca Verdadeiro onde for 0
    if 'ipu_cod' in df.columns:
        condicao = condicao | (df['ipu_cod'].astype(str).isin(['0', '00', '000']))
    
    # Se tiver coluna Fonte, marca Verdadeiro onde for 89
    if 'fonte_cod' in df.columns:
        condicao = condicao | (df['fonte_cod'].astype(str) == '89')
        
    # Retorna apenas as linhas que satisfazem a condição
    return df[condicao].copy()

# Aplica o filtro em todas as tabelas principais
df_execucao = filtrar_propag(df_execucao)
df_rp = filtrar_propag(df_rp)
df_limites = filtrar_propag(df_limites)

# ==============================================================================
# 4. CÁLCULO DE RESTOS A PAGAR (RP)
# ==============================================================================
print("3/5 - Calculando métricas matemáticas de Restos a Pagar...")

if not df_rp.empty:
    # Garante que todas as colunas de valor (vlr_...) sejam números
    cols_vlr = [c for c in df_rp.columns if 'vlr_' in c]
    for col in cols_vlr: 
        df_rp[col] = pd.to_numeric(df_rp[col], errors='coerce').fillna(0)

    # Fórmula: Pago Processado
    df_rp['rp_proc_pago'] = (
        df_rp['vlr_pago_rpp'] - df_rp['vlr_anulacao_pagamento_rpp'] + 
        df_rp['vlr_retencao_rpp'] - df_rp['vlr_anulacao_retencao_rpp']
    )
    
    # Garante coluna auxiliar
    if 'vlr_despesa_liquidada_pagar' not in df_rp.columns: 
        df_rp['vlr_despesa_liquidada_pagar'] = 0
        
    # Fórmula: Liquidado Não Processado
    df_rp['rp_nproc_liquidado'] = df_rp['vlr_despesa_liquidada_rpnp']
    
    # Fórmula: Pago Não Processado
    df_rp['rp_nproc_pago'] = (
        df_rp['vlr_saldo_rpp'] + 
        df_rp['vlr_despesa_liquidada_rpnp'] - 
        df_rp['vlr_despesa_liquidada_pagar']
    )
    
    # Totalizadores usados no Painel
    df_rp['vlr_liquidado_rp_total'] = df_rp['rp_nproc_liquidado'] 
    df_rp['vlr_pago_rp_total'] = df_rp['rp_proc_pago'] + df_rp['rp_nproc_pago']
else:
    # Se a tabela estiver vazia, zera os totais
    df_rp['vlr_liquidado_rp_total'] = 0

# ==============================================================================
# 5. REGRA DE INTERVENÇÕES (MAPEAMENTO DE OBRAS)
# ==============================================================================
print("4/5 - Mapeando códigos de intervenção (Regras UO 1251 e 1301)...")

def identificar_intervencao(row):
    """
    Analisa cada linha de despesa e diz a qual intervenção ela pertence.
    """
    # Pega os valores da linha convertendo para texto seguro
    uo = str(row.get('uo_cod', ''))
    acao = str(row.get('acao_cod', ''))
    item = str(row.get('elemento_item_cod', ''))
    obra = str(row.get('num_obra', ''))
    
    # Remove '.0' se o Excel tiver colocado (ex: '12221.0' -> '12221')
    if obra.endswith('.0'): obra = obra[:-2]
    
    # Regra DER MG (UO 1251)
    if uo == '1251' and acao == '4365':
        # Se o item for 5201 vai para uma, senão vai para outra
        return '125102' if item == '5201' else '125101'
        
    # Regra Obras Específicas (UO 1301 - Saúde)
    if uo == '1301' and acao == '1037':
        # Mapa direto: Número da Obra -> Código da Intervenção
        mapa = {
            '12221': '130109', '12533': '130108', '12507': '130112', 
            '8025': '130107', '12219': '130110', '11527': '130111'
        }
        if obra in mapa: return mapa[obra]
        
    return None # Se não cair em nenhuma regra, retorna vazio

# Aplica a função linha a linha (axis=1) se a tabela não estiver vazia
if not df_execucao.empty: 
    df_execucao['intervencao_map'] = df_execucao.apply(identificar_intervencao, axis=1)
if not df_rp.empty: 
    df_rp['intervencao_map'] = df_rp.apply(identificar_intervencao, axis=1)

# ==============================================================================
# 6. GERAÇÃO DE TABELAS FINAIS (OUTPUT)
# ==============================================================================
print("5/5 - Gerando tabelas finais e salvando...")

# --- TABELA 1: VISÃO GERAL ---
# Agrupamos tudo por Ano, UO, Fonte e IPU
chaves = ['ano', 'uo_cod', 'fonte_cod', 'ipu_cod']

# Garante que usamos apenas chaves que existem no arquivo de limites
cols_join_lim = [c for c in chaves if c in df_limites.columns]

# Agrupa Limites
t_limite = df_limites.groupby(cols_join_lim, as_index=False)['valor_limite'].sum()

# Agrupa Execução (Se vazia, cria tabela vazia estruturada)
t_exec = df_execucao.groupby(chaves, as_index=False)['vlr_liquidado'].sum() if not df_execucao.empty else pd.DataFrame(columns=chaves)

# Agrupa RP
t_rp = df_rp.groupby(chaves, as_index=False)['vlr_liquidado_rp_total'].sum() if not df_rp.empty else pd.DataFrame(columns=chaves)

# Junta Limites com Execução (Outer Join mantém quem tem limite mas não tem execução e vice-versa)
df_visao = pd.merge(t_limite, t_exec, on=cols_join_lim, how='outer')

# Junta com RP
if not t_rp.empty: 
    df_visao = pd.merge(df_visao, t_rp, on=cols_join_lim, how='outer')

# Preenche vazios (NaN) com zero
df_visao.fillna(0, inplace=True)

# Garante que as colunas existem
if 'vlr_liquidado' not in df_visao.columns: df_visao['vlr_liquidado'] = 0
if 'vlr_liquidado_rp_total' not in df_visao.columns: df_visao['vlr_liquidado_rp_total'] = 0

# Calcula Totais
df_visao['vlr_liquidado_total'] = df_visao['vlr_liquidado'] + df_visao['vlr_liquidado_rp_total']
df_visao['saldo_limite'] = df_visao['valor_limite'] - df_visao['vlr_liquidado_total']

# Adiciona a Sigla da UO para ficar legível
mapa_siglas = df_uo.set_index('uo_cod')['uo_sigla'].to_dict() if not df_uo.empty else {}
df_visao['uo_sigla'] = df_visao['uo_cod'].map(mapa_siglas)

# Salva o arquivo final
df_visao.to_csv(PATH_OUT / "tabela_visao_geral.csv", index=False)

# --- TABELA 2: INTERVENÇÕES ---
# Prepara a chave de agrupamento temporária
if df_execucao.empty: 
    df_execucao['intervencao_temp'] = []
else: 
    # Preenche vazios com 'SEM_REF' para não perder dados no agrupamento
    df_execucao['intervencao_temp'] = df_execucao['intervencao_map'].fillna('SEM_REF')

if df_rp.empty: 
    df_rp['intervencao_temp'] = []
else: 
    df_rp['intervencao_temp'] = df_rp['intervencao_map'].fillna('SEM_REF')

# Agrupa Execução e RP por Intervenção
exec_int = df_execucao.groupby(['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], as_index=False)['vlr_liquidado'].sum() if not df_execucao.empty else pd.DataFrame()
rp_int = df_rp.groupby(['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], as_index=False)['vlr_liquidado_rp_total'].sum() if not df_rp.empty else pd.DataFrame()

# Junta Execução + RP
total_int = pd.merge(exec_int, rp_int, on=['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], how='outer').fillna(0)

# Calcula Total Liquidado
if 'vlr_liquidado' in total_int.columns:
    total_int['liquidado_final'] = total_int['vlr_liquidado'] + total_int['vlr_liquidado_rp_total']
else: 
    total_int['liquidado_final'] = 0

# Prepara a tabela de Metas (Limites das Intervenções)
df_meta = df_intervencoes.rename(columns={'intervencao_cod': 'intervencao_temp'})
# Limpa o código da intervenção (.0)
if not df_meta.empty and 'intervencao_temp' in df_meta.columns:
    df_meta['intervencao_temp'] = df_meta['intervencao_temp'].astype(str).str.replace('.0', '', regex=False)

# Junta Meta (Planejado) com Executado
df_painel_int = pd.merge(df_meta, total_int, on=['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], how='outer')

# Preenche vazios e calcula saldo
cols_fill = ['valor_plano', 'liquidado_final']
for c in cols_fill: 
    if c not in df_painel_int.columns: df_painel_int[c] = 0
    df_painel_int[c] = df_painel_int[c].fillna(0)

df_painel_int['saldo_plano'] = df_painel_int['valor_plano'] - df_painel_int['liquidado_final']

# Traz descrições de UO e Ação
df_painel_int['uo_sigla'] = df_painel_int['uo_cod'].dropna().astype(str).map(mapa_siglas)
if not df_acao.empty: 
    df_painel_int['acao_desc'] = df_painel_int['acao_cod'].dropna().astype(str).map(df_acao.set_index('acao_cod')['acao_desc'].to_dict())

# Renomeia para nome final e salva
df_painel_int.rename(columns={'intervencao_temp': 'cod_intervencao'}, inplace=True)
df_painel_int.to_csv(PATH_OUT / "tabela_intervencoes.csv", index=False)

print(">>> SUCESSO! DADOS PROCESSADOS E SALVOS NA PASTA processed_data. <<<")