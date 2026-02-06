import pandas as pd
import numpy as np
import os
import warnings

# ==============================================================================
# CONFIGURAÇÕES INICIAIS
# ==============================================================================
warnings.filterwarnings('ignore')

print(">>> INICIANDO O PROCESSAMENTO DE DADOS (ETL) - FINAL <<<")

# Definição dos caminhos das pastas
PATH_RAW = "data-raw"
PATH_AUX = "datapackages/aux-classificadores/data"
PATH_SIAFI = "datapackages/siafi-2026/data"
PATH_OUT = "processed_data"

os.makedirs(PATH_OUT, exist_ok=True)

# ==============================================================================
# 1. FUNÇÃO DE LEITURA
# ==============================================================================
def ler_csv_seguro(path, encoding='utf-8', compression=None):
    """
    Lê CSV tentando separadores ; e , automaticamente e limpa nomes de colunas.
    """
    # Define colunas que devem ser lidas como texto (String)
    cols_str = {
        'uo_cod': str, 'acao_cod': str, 'fonte_cod': str, 'ipu_cod': str, 
        'grupo_cod': str, 'iag_cod': str, 'elemento_item_cod': str, 
        'intervencao_cod': str, 'num_obra': str, 
        'funcao_cod': str, 'programa_cod': str # Adicionados conforme schema
    }
    
    separadores = [';', ',']
    
    for sep in separadores:
        try:
            df = pd.read_csv(path, encoding=encoding, sep=sep, compression=compression, dtype=cols_str)
            
            # Se leu tudo em 1 coluna só, o separador está errado
            if df.shape[1] <= 1 and sep == ';': continue
            
            # Padroniza nomes das colunas: minúsculo e sem espaços nas pontas
            df.columns = [c.strip().lower() for c in df.columns]
            
            # Limpa espaços nos dados de texto
            for col in df.select_dtypes(include=['object']).columns:
                df[col] = df[col].str.strip()
            
            print(f"   [OK] Lido: {path} ({len(df)} linhas)")
            return df
        except Exception:
            continue

    print(f"   [ERRO CRÍTICO] Não foi possível ler: {path}")
    return pd.DataFrame()

# ==============================================================================
# 2. CARREGAMENTO DOS DADOS
# ==============================================================================
print("1/5 - Carregando arquivos...")

# Tabelas Auxiliares
df_uo = ler_csv_seguro(f"{PATH_AUX}/uo.csv")
df_acao = ler_csv_seguro(f"{PATH_AUX}/acao.csv")

# --- TABELA DE LIMITES (Schema: limite_propag) ---
df_limites = ler_csv_seguro(f"{PATH_RAW}/propag_investimentos_limite_2026.csv", encoding='utf-8') 

# Correção Explícita baseada no Schema enviado
if 'limite_propag' in df_limites.columns:
    # Renomeia para um nome padrão interno para facilitar contas
    df_limites.rename(columns={'limite_propag': 'valor_limite'}, inplace=True)
elif 'valor_limite' not in df_limites.columns:
    # Caso o arquivo tenha outro nome, tenta avisar
    print("   [ERRO] Coluna 'limite_propag' não encontrada no arquivo de limites.")
    print(f"   Colunas encontradas: {list(df_limites.columns)}")

# Converter limite para número (caso venha como texto com vírgula)
if not df_limites.empty and 'valor_limite' in df_limites.columns:
    if df_limites['valor_limite'].dtype == 'O':
        df_limites['valor_limite'] = df_limites['valor_limite'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    df_limites['valor_limite'] = pd.to_numeric(df_limites['valor_limite'], errors='coerce').fillna(0)


# --- TABELA DE INTERVENÇÕES (Schema: valor_plano) ---
df_intervencoes = ler_csv_seguro(f"{PATH_RAW}/propag_investimentos_intervencoes_plano_2026.csv", encoding='cp1252')

# Converter plano para número
if not df_intervencoes.empty and 'valor_plano' in df_intervencoes.columns:
    if df_intervencoes['valor_plano'].dtype == 'O':
        df_intervencoes['valor_plano'] = df_intervencoes['valor_plano'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    df_intervencoes['valor_plano'] = pd.to_numeric(df_intervencoes['valor_plano'], errors='coerce').fillna(0)
else:
    print("   [AVISO] Coluna 'valor_plano' não encontrada nas intervenções. Criando coluna zerada.")
    df_intervencoes['valor_plano'] = 0.0

# --- TABELAS SIAFI ---
df_execucao = ler_csv_seguro(f"{PATH_SIAFI}/execucao.csv.gz", compression='gzip')
df_rp = ler_csv_seguro(f"{PATH_SIAFI}/restos_pagar.csv.gz", compression='gzip')

# ==============================================================================
# 3. FILTROS GLOBAIS
# ==============================================================================
print("2/5 - Aplicando filtros (IPU=0 ou Fonte=89)...")

def filtrar_propag(df):
    if df.empty: return df
    condicao = pd.Series(False, index=df.index)
    
    # Verifica IPU
    if 'ipu_cod' in df.columns:
        condicao = condicao | (df['ipu_cod'].astype(str).isin(['0', '00', '000']))
    
    # Verifica Fonte
    if 'fonte_cod' in df.columns:
        condicao = condicao | (df['fonte_cod'].astype(str) == '89')
        
    return df[condicao].copy()

df_execucao = filtrar_propag(df_execucao)
df_rp = filtrar_propag(df_rp)
df_limites = filtrar_propag(df_limites)

# ==============================================================================
# 4. CÁLCULO DE RESTOS A PAGAR
# ==============================================================================
print("3/5 - Calculando métricas de Restos a Pagar...")

if not df_rp.empty:
    cols_vlr = [c for c in df_rp.columns if 'vlr_' in c]
    for col in cols_vlr:
        df_rp[col] = pd.to_numeric(df_rp[col], errors='coerce').fillna(0)

    # Fórmulas
    df_rp['rp_proc_pago'] = (
        df_rp['vlr_pago_rpp'] - df_rp['vlr_anulacao_pagamento_rpp'] + 
        df_rp['vlr_retencao_rpp'] - df_rp['vlr_anulacao_retencao_rpp']
    )
    if 'vlr_despesa_liquidada_pagar' not in df_rp.columns: df_rp['vlr_despesa_liquidada_pagar'] = 0

    df_rp['rp_nproc_liquidado'] = df_rp['vlr_despesa_liquidada_rpnp']
    df_rp['rp_nproc_pago'] = (
        df_rp['vlr_saldo_rpp'] + df_rp['vlr_despesa_liquidada_rpnp'] - df_rp['vlr_despesa_liquidada_pagar']
    )
    
    df_rp['vlr_liquidado_rp_total'] = df_rp['rp_nproc_liquidado'] 
    df_rp['vlr_pago_rp_total'] = df_rp['rp_proc_pago'] + df_rp['rp_nproc_pago']
else:
    df_rp['vlr_liquidado_rp_total'] = 0
    df_rp['vlr_pago_rp_total'] = 0

# ==============================================================================
# 5. REGRA DE INTERVENÇÕES (OBRAS 1301)
# ==============================================================================
print("4/5 - Mapeando códigos de intervenção...")

def identificar_intervencao(row):
    uo = str(row.get('uo_cod', ''))
    acao = str(row.get('acao_cod', ''))
    item = str(row.get('elemento_item_cod', ''))
    obra = str(row.get('num_obra', ''))
    
    if obra.endswith('.0'): obra = obra[:-2]
    
    # Regra DER MG
    if uo == '1251' and acao == '4365':
        return '125102' if item == '5201' else '125101'
            
    # Regra OBRAS ESPECÍFICAS
    if uo == '1301' and acao == '1037':
        mapa = {
            '12221': '130109', '12533': '130108', '12507': '130112',
            '8025':  '130107', '12219': '130110', '11527': '130111'
        }
        if obra in mapa: return mapa[obra]
        
    return None

if not df_execucao.empty: df_execucao['intervencao_map'] = df_execucao.apply(identificar_intervencao, axis=1)
if not df_rp.empty: df_rp['intervencao_map'] = df_rp.apply(identificar_intervencao, axis=1)

# ==============================================================================
# 6. GERAÇÃO DE TABELAS
# ==============================================================================
print("5/5 - Gerando tabelas finais...")

# --- TABELA VISÃO GERAL ---
chaves = ['ano', 'uo_cod', 'fonte_cod', 'ipu_cod']

# Garante que as chaves existem no dataframe de limites
cols_join_lim = [c for c in chaves if c in df_limites.columns]

# Agrupamentos
t_limite = df_limites.groupby(cols_join_lim, as_index=False)['valor_limite'].sum()

if not df_execucao.empty:
    t_exec = df_execucao.groupby(chaves, as_index=False)['vlr_liquidado'].sum()
else:
    t_exec = pd.DataFrame(columns=chaves + ['vlr_liquidado'])

if not df_rp.empty:
    t_rp = df_rp.groupby(chaves, as_index=False)['vlr_liquidado_rp_total'].sum()
else:
    t_rp = pd.DataFrame(columns=chaves + ['vlr_liquidado_rp_total'])

# Joins
df_visao = pd.merge(t_limite, t_exec, on=cols_join_lim, how='outer')
if not t_rp.empty:
    # Ajuste de chaves para o join do RP (pode ser outer também)
    df_visao = pd.merge(df_visao, t_rp, on=cols_join_lim, how='outer')

df_visao.fillna(0, inplace=True)

# Cálculos
if 'vlr_liquidado' not in df_visao.columns: df_visao['vlr_liquidado'] = 0
if 'vlr_liquidado_rp_total' not in df_visao.columns: df_visao['vlr_liquidado_rp_total'] = 0

df_visao['vlr_liquidado_total'] = df_visao['vlr_liquidado'] + df_visao['vlr_liquidado_rp_total']
df_visao['saldo_limite'] = df_visao['valor_limite'] - df_visao['vlr_liquidado_total']

# Nomes
mapa_siglas = df_uo.set_index('uo_cod')['uo_sigla'].to_dict() if not df_uo.empty else {}
df_visao['uo_sigla'] = df_visao['uo_cod'].map(mapa_siglas)

df_visao.to_csv(f"{PATH_OUT}/tabela_visao_geral.csv", index=False)

# --- TABELA INTERVENÇÕES ---
if df_execucao.empty: df_execucao['intervencao_temp'] = []
else: df_execucao['intervencao_temp'] = df_execucao['intervencao_map'].fillna('SEM_REF')

if df_rp.empty: df_rp['intervencao_temp'] = []
else: df_rp['intervencao_temp'] = df_rp['intervencao_map'].fillna('SEM_REF')

exec_int = df_execucao.groupby(['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], as_index=False)['vlr_liquidado'].sum() if not df_execucao.empty else pd.DataFrame(columns=['ano','uo_cod','acao_cod','intervencao_temp','vlr_liquidado'])
rp_int = df_rp.groupby(['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], as_index=False)['vlr_liquidado_rp_total'].sum() if not df_rp.empty else pd.DataFrame(columns=['ano','uo_cod','acao_cod','intervencao_temp','vlr_liquidado_rp_total'])

total_int = pd.merge(exec_int, rp_int, on=['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], how='outer').fillna(0)
total_int['liquidado_final'] = total_int['vlr_liquidado'] + total_int['vlr_liquidado_rp_total']

df_meta = df_intervencoes.rename(columns={'intervencao_cod': 'intervencao_temp'})
if not df_meta.empty and 'intervencao_temp' in df_meta.columns:
    df_meta['intervencao_temp'] = df_meta['intervencao_temp'].astype(str).str.replace('.0', '', regex=False)

df_painel_int = pd.merge(df_meta, total_int, on=['ano', 'uo_cod', 'acao_cod', 'intervencao_temp'], how='outer')
cols_fill = ['valor_plano', 'liquidado_final', 'vlr_liquidado', 'vlr_liquidado_rp_total']
for c in cols_fill:
    if c not in df_painel_int.columns: df_painel_int[c] = 0
    df_painel_int[c] = df_painel_int[c].fillna(0)

df_painel_int['saldo_plano'] = df_painel_int['valor_plano'] - df_painel_int['liquidado_final']
df_painel_int['uo_sigla'] = df_painel_int['uo_cod'].dropna().astype(str).map(mapa_siglas)

if not df_acao.empty:
    df_painel_int['acao_desc'] = df_painel_int['acao_cod'].dropna().astype(str).map(df_acao.set_index('acao_cod')['acao_desc'].to_dict())

df_painel_int.rename(columns={'intervencao_temp': 'cod_intervencao'}, inplace=True)
df_painel_int.to_csv(f"{PATH_OUT}/tabela_intervencoes.csv", index=False)

print(">>> SUCESSO! ETL CONCLUÍDO. <<<")