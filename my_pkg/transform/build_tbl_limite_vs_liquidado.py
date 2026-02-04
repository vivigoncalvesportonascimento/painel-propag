# my_pkg/transform/build_tbl_limite_vs_liquidado.py
# -*- coding: utf-8 -*-
"""
Gera a tabela 'tbl_limite_liquidado_2026' no grão:
(ano=2026, uo_cod, fonte_cod, ipu_cod)

Colunas de saída:
- Ano
- UO cod
- UO sigla
- Fonte
- IPU
- Limite Propag 2026          (limites do Propag)
- Liquidado 2026              (execução 2026 + RP não processado liquidado em 2026)
- Saldo de limite             (Limite - Liquidado)

Regras de negócio/filtro:
- Incluir somente linhas com (fonte_cod == 89) OU (ipu_cod == 0).

Arquivos (sem mover pastas):
- Limites: data-raw/propag_investimentos_limite_2026.csv
- SIAFI (procura automaticamente em múltiplas pastas):
    execucao.csv.gz, restos_pagar.csv.gz
- Dimensões (procura automaticamente em múltiplas pastas):
    uo.csv, fonte_recurso.csv (opcional)

Saídas:
- data-processed/tbl_limite_liquidado_2026.parquet (se houver backend)
- data-processed/tbl_limite_liquidado_2026.csv

Rodar:
    poetry run build-tbl-limite-liquidado
ou
    poetry run python -m my_pkg.transform.build_tbl_limite_vs_liquidado
"""

from __future__ import annotations
import os
import glob
import hashlib
import warnings
from typing import List
import pandas as pd

# ---------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------
ANO_ALVO = 2026
DATA_RAW = "data-raw"
OUT_DIR = "data-processed"
os.makedirs(OUT_DIR, exist_ok=True)

# Diretórios onde procuraremos os arquivos SEM você precisar mudar pastas
DATA_DIRS = [
    # raiz “canônica”
    "data",
    # estrutura que você mostrou no print
    os.path.join("datapackages", "siafi-2026", "data"),
    os.path.join("datapackages", "aux-classificadores", "data"),
    # variações comuns (caso existam)
    os.path.join("siafi-2026", "data"),
    os.path.join("aux-classificadores", "data"),
]

# ---------------------------------------------------------------------
# Utilitários de I/O e qualidade
# ---------------------------------------------------------------------


def find_existing(*filenames: str) -> str:
    """
    Retorna o primeiro caminho existente para qualquer um dos filenames
    nos diretórios de DATA_DIRS. Caso não encontre, faz uma busca
    recursiva sob 'datapackages/**/data/<filename>'.
    """
    # Passo 1: checagem direta nas pastas conhecidas
    for d in DATA_DIRS:
        for name in filenames:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p

    # Passo 2: busca recursiva dentro de 'datapackages/**/data/<filename>'
    for name in filenames:
        pattern = os.path.join("datapackages", "**", "data", name)
        matches = glob.glob(pattern, recursive=True)
        for m in matches:
            if os.path.exists(m):
                return m

    # Se nada foi encontrado, informe claramente onde buscamos
    raise FileNotFoundError(
        "Arquivo(s) não encontrado(s):\n - {}\nProcurado em:\n - {}\nBusca recursiva: 'datapackages/**/data/<arquivo>'".format(
            "\n - ".join(filenames),
            "\n - ".join(DATA_DIRS),
        )
    )


def aplica_filtro_negocio(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mantém apenas linhas com fonte_cod=89 OU ipu_cod=0.
    Em bases que não tenham ipu_cod, cria com NA e aplica o filtro.
    """
    if "fonte_cod" not in df.columns:
        return df.iloc[0:0].copy()
    if "ipu_cod" not in df.columns:
        df = df.assign(ipu_cod=pd.NA)
    return df.loc[(df["fonte_cod"] == 89) | (df["ipu_cod"] == 0)].copy()


def parse_moeda_series(s: pd.Series) -> pd.Series:
    """
    Converte strings de moeda brasileiras (ex.: "1.234.567,89") ou
    formatos mistos em float. Valores inválidos viram 0.0.
    """
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    s = (
        s.astype(str)
         .str.replace(r"[^0-9,.\-]", "", regex=True)
         .str.replace(r"\.", "", regex=True)
         .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def make_sk_link(ano: pd.Series, uo: pd.Series, fonte: pd.Series, ipu: pd.Series) -> pd.Series:
    """
    Gera chave substituta determinística (hash) para a combinação (ano|uo|fonte|ipu).
    """
    key = (ano.astype(str) + "|" + uo.astype(str) + "|" +
           fonte.astype(str) + "|" + ipu.astype(str))
    return key.apply(lambda x: hashlib.sha1(x.encode("utf-8")).hexdigest())


def format_brl(x: float) -> str:
    """
    Formata valores no estilo PT-BR rapidamente (sem depender de locale do SO).
    """
    s = f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

# ---------------------------------------------------------------------
# Leitura robusta do CSV de limites
# ---------------------------------------------------------------------


def read_csv_robusto(path: str, prefer_utf: bool = True, sniff_sep: bool = True, usecols: List[str] | None = None) -> pd.DataFrame:
    """
    Lê CSV lidando com:
    - BOM/UTF-8 (utf-8-sig) e fallback cp1252
    - sniff de delimitador (sep=None, engine='python')
    """
    encs = ["utf-8-sig", "utf-8",
            "cp1252"] if prefer_utf else ["cp1252", "utf-8-sig", "utf-8"]
    last_err = None
    for enc in encs:
        try:
            if sniff_sep:
                return pd.read_csv(path, encoding=enc, sep=None, engine="python", usecols=usecols)
            return pd.read_csv(path, encoding=enc, usecols=usecols)
        except Exception as e:
            last_err = e
    raise last_err

# ---------------------------------------------------------------------
# Loaders das bases
# ---------------------------------------------------------------------


def load_limite_propag_2026() -> pd.DataFrame:
    """
    Limites do Propag 2026.
    Arquivo: data-raw/propag_investimentos_limite_2026.csv
    Campos relevantes: ano, uo_cod, uo_sigla, fonte_cod, ipu_cod, limite_propag (texto)
    """
    path = os.path.join(DATA_RAW, "propag_investimentos_limite_2026.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Arquivo não encontrado: {path}\n"
            f"Verifique se o CSV de limites está em {DATA_RAW}/"
        )

    # Lê farejando separador e aceitando BOM (se houver).
    df = read_csv_robusto(path, prefer_utf=True, sniff_sep=True)

    # Checagem mínima de colunas
    cols_needed = ["ano", "uo_cod", "uo_sigla",
                   "fonte_cod", "ipu_cod", "limite_propag"]
    missing = [c for c in cols_needed if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colunas ausentes em limites: {missing}\n"
            f"Colunas lidas: {list(df.columns)}\n"
            f"Arquivo: {path}"
        )

    # Filtro de negócio + ano
    df = aplica_filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO].copy()

    # Converter limite para número
    df["limite_propag"] = parse_moeda_series(df["limite_propag"])

    # Agregar no grão
    grp = (
        df.groupby(["ano", "uo_cod", "fonte_cod", "ipu_cod"],
                   as_index=False, dropna=False)["limite_propag"]
        .sum()
    )
    return grp


def load_execucao_2026() -> pd.DataFrame:
    """
    Execução SIAFI 2026: somatório de vlr_liquidado no exercício.
    Procura por: data/execucao.csv.gz, datapackages/**/data/execucao.csv.gz, etc.
    """
    path = find_existing("execucao.csv.gz")
    usecols = ["ano", "uo_cod", "fonte_cod", "ipu_cod", "vlr_liquidado"]
    df = pd.read_csv(path, compression="gzip",
                     usecols=usecols, encoding="utf-8")
    df = aplica_filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO].copy()
    grp = df.groupby(["ano", "uo_cod", "fonte_cod", "ipu_cod"],
                     as_index=False, dropna=False)["vlr_liquidado"].sum()
    return grp


def load_restos_rpnp_liquidado_2026() -> pd.DataFrame:
    """
    Restos a Pagar SIAFI 2026: somatório de vlr_despesa_liquidada_rpnp no exercício.
    Procura por: data/restos_pagar.csv.gz, datapackages/**/data/restos_pagar.csv.gz, etc.
    """
    path = find_existing("restos_pagar.csv.gz")
    usecols = ["ano", "uo_cod", "fonte_cod",
               "ipu_cod", "vlr_despesa_liquidada_rpnp"]
    df = pd.read_csv(path, compression="gzip",
                     usecols=usecols, encoding="utf-8")
    df = aplica_filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO].copy()
    grp = df.groupby(["ano", "uo_cod", "fonte_cod", "ipu_cod"],
                     as_index=False, dropna=False)["vlr_despesa_liquidada_rpnp"].sum()
    return grp


def load_dim_uo() -> pd.DataFrame:
    """
    Dimensão UO: procura por uo.csv nas pastas suportadas.
    Campos: ano, uo_cod, uo_sigla
    """
    path = find_existing("uo.csv")
    df = pd.read_csv(
        path, usecols=["ano", "uo_cod", "uo_sigla"], encoding="utf-8")
    return df.drop_duplicates(subset=["ano", "uo_cod"])


def load_dim_fonte() -> pd.DataFrame:
    """
    Dimensão Fonte (opcional): procura por fonte_recurso.csv.
    Campos: ano, fonte_cod, fonte_desc
    """
    try:
        path = find_existing("fonte_recurso.csv")
    except FileNotFoundError:
        warnings.warn(
            "Dimensão 'fonte_recurso.csv' não encontrada — seguiremos sem a descrição da fonte.")
        return pd.DataFrame(columns=["ano", "fonte_cod", "fonte_desc"])

    df = pd.read_csv(
        path, usecols=["ano", "fonte_cod", "fonte_desc"], encoding="utf-8")
    return df.drop_duplicates(subset=["ano", "fonte_cod"])

# ---------------------------------------------------------------------
# Construção da Link Table e da tabela final
# ---------------------------------------------------------------------


def build_link_table(df_lim: pd.DataFrame, df_exec: pd.DataFrame, df_rpnp: pd.DataFrame) -> pd.DataFrame:
    keys_cols = ["ano", "uo_cod", "fonte_cod", "ipu_cod"]
    lk = pd.concat([df_lim[keys_cols], df_exec[keys_cols],
                   df_rpnp[keys_cols]], ignore_index=True)
    lk = lk.drop_duplicates().reset_index(drop=True)
    lk["sk_link"] = make_sk_link(
        lk["ano"], lk["uo_cod"], lk["fonte_cod"], lk["ipu_cod"])
    return lk


def build_table() -> pd.DataFrame:
    # Carrega fatos
    df_lim = load_limite_propag_2026()
    df_exec = load_execucao_2026()
    df_rpnp = load_restos_rpnp_liquidado_2026()

    # Cria link table
    link = build_link_table(df_lim, df_exec, df_rpnp)

    # Junta métricas
    tbl = link.merge(df_lim,  on=["ano", "uo_cod",
                     "fonte_cod", "ipu_cod"], how="left")
    tbl = tbl.merge(df_exec, on=["ano", "uo_cod",
                    "fonte_cod", "ipu_cod"], how="left")
    tbl = tbl.merge(df_rpnp, on=["ano", "uo_cod",
                    "fonte_cod", "ipu_cod"], how="left")

    # Preencher métricas ausentes com 0
    for col in ["limite_propag", "vlr_liquidado", "vlr_despesa_liquidada_rpnp"]:
        if col in tbl.columns:
            tbl[col] = tbl[col].fillna(0.0)

    # Cálculos finais
    tbl["liquidado_2026"] = tbl["vlr_liquidado"] + \
        tbl["vlr_despesa_liquidada_rpnp"]
    tbl["saldo_limite"] = tbl["limite_propag"] - tbl["liquidado_2026"]

    # Dimensões
    dim_uo = load_dim_uo()
    dim_fonte = load_dim_fonte()

    tbl = tbl.merge(dim_uo, on=["ano", "uo_cod"], how="left")
    if not dim_fonte.empty:
        tbl = tbl.merge(dim_fonte, on=["ano", "fonte_cod"], how="left")

    # Selecionar/ordenar colunas
    cols_final = [
        "ano", "uo_cod", "uo_sigla",
        "fonte_cod",
        "ipu_cod",
        "limite_propag", "liquidado_2026", "saldo_limite",
    ]
    if "fonte_desc" in tbl.columns:
        cols_final = ["ano", "uo_cod", "uo_sigla", "fonte_cod", "fonte_desc",
                      "ipu_cod", "limite_propag", "liquidado_2026", "saldo_limite"]

    tbl_final = tbl[cols_final].copy()

    # Renomeia para cabeçalhos “humanizados”
    rename_map = {
        "ano": "Ano",
        "uo_cod": "UO cod",
        "uo_sigla": "UO sigla",
        "fonte_cod": "Fonte",
        "fonte_desc": "Fonte (desc)",
        "ipu_cod": "IPU",
        "limite_propag": "Limite Propag 2026",
        "liquidado_2026": "Liquidado 2026",
        "saldo_limite": "Saldo de limite",
    }
    tbl_final = tbl_final.rename(columns=rename_map)

    # Ordenação amigável
    sort_cols = ["Ano", "UO cod", "Fonte", "IPU"]
    tbl_final = tbl_final.sort_values(
        sort_cols, kind="stable").reset_index(drop=True)
    return tbl_final


def main():
    df = build_table()

    # Salvar Parquet (se possível) + CSV sempre
    out_parquet = os.path.join(OUT_DIR, "tbl_limite_liquidado_2026.parquet")
    out_csv = os.path.join(OUT_DIR, "tbl_limite_liquidado_2026.csv")

    parquet_ok = False
    try:
        df.to_parquet(out_parquet, index=False)
        parquet_ok = True
    except Exception as e:
        warnings.warn(
            f"Não foi possível gravar Parquet ({e}). "
            f"Se desejar Parquet, instale um backend (ex.: 'poetry add pyarrow')."
        )

    df.to_csv(out_csv, index=False, encoding="utf-8")

    # Resumo no console
    print("Registros:", len(df))
    print("Total Limite:          ", format_brl(
        df["Limite Propag 2026"].sum()))
    print("Total Liquidado 2026:  ", format_brl(df["Liquidado 2026"].sum()))
    print("Total Saldo:           ", format_brl(df["Saldo de limite"].sum()))
    if parquet_ok:
        print(f"\nArquivos salvos em:\n - {out_parquet}\n - {out_csv}")
    else:
        print(f"\nArquivo salvo em:\n - {out_csv}")


if __name__ == "__main__":
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", 20)
    main()
