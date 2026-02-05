# my_pkg/transform/build_pagina2_intervencao.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import glob
import pandas as pd

ANO_ALVO = 2026
OUT_DIR = "data-processed"
os.makedirs(OUT_DIR, exist_ok=True)

DATA_SIAFI = os.path.join("datapackages", "siafi-2026", "data")

# ---------------------------
# Utilitários
# ---------------------------


def filtro_negocio(df: pd.DataFrame) -> pd.DataFrame:
    """Filtro global: fonte=89 OU ipu=0."""
    if "fonte_cod" not in df.columns:
        return df.iloc[0:0].copy()
    if "ipu_cod" not in df.columns:
        df = df.assign(ipu_cod=pd.NA)
    return df.loc[(df["fonte_cod"] == 89) | (df["ipu_cod"] == 0)].copy()


def read_csv_smart(path: str,
                   encodings=("utf-8-sig", "utf-8", "cp1252", "latin1"),
                   seps=(None, ";", "\t", ","),
                   usecols=None) -> pd.DataFrame:
    """
    Lê CSV lidando com encoding e delimitador:
      - tenta farejar sep (sep=None, engine='python')
      - se falhar, tenta separadores explícitos (;, \t, ,)
      - testa encodings em cascata
    """
    last_err = None
    for enc in encodings:
        for sep in seps:
            try:
                if sep is None:
                    return pd.read_csv(path, encoding=enc, sep=None, engine="python",
                                       usecols=usecols)
                else:
                    return pd.read_csv(path, encoding=enc, sep=sep,
                                       engine="python", usecols=usecols)
            except Exception as e:
                last_err = e
                continue
    raise last_err if last_err else FileNotFoundError(path)


def find_existing(*names: str, root: str | None = None) -> str:
    """
    Procura um arquivo dentro de DATA_SIAFI ou em subpastas de datapackages/**/data.
    """
    bases = [DATA_SIAFI] if root is None else [root]
    for d in bases:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    for n in names:
        for m in glob.glob(os.path.join("datapackages", "**", "data", n), recursive=True):
            if os.path.exists(m):
                return m
    raise FileNotFoundError(names)

# ---------------------------
# Cargas (usando nomes do datapackage oficial SIAFI 2026)
# ---------------------------


def load_rp_np_liq_grain7() -> pd.DataFrame:
    """
    RP Não Processado (liquidado) agregado no grão 7 chaves.
    Campo oficial: 'vlr_despesa_liquidada_rpnp'.
    """
    p = find_existing("restos_pagar.csv.gz")
    df = pd.read_csv(p, compression="gzip", encoding="utf-8")
    df = filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO]

    key7 = ["ano", "uo_cod", "acao_cod", "grupo_cod",
            "iag_cod", "fonte_cod", "ipu_cod"]
    df["liq_np"] = pd.to_numeric(
        df["vlr_despesa_liquidada_rpnp"], errors="coerce").fillna(0.0)
    rp = df.groupby(key7, as_index=False)[["liq_np"]].sum()
    return rp


def load_exec_detalhado() -> pd.DataFrame:
    """
    Execução detalhada (precisamos de elemento_item_cod e num_obra).
    Campos oficiais: 'vlr_liquidado', 'elemento_item_cod', 'num_obra'.
    """
    p = find_existing("execucao.csv.gz")
    use = ["ano", "uo_cod", "acao_cod", "grupo_cod", "iag_cod", "fonte_cod", "ipu_cod",
           "elemento_item_cod", "num_obra", "vlr_liquidado"]
    ex = pd.read_csv(p, compression="gzip", encoding="utf-8", usecols=use)
    ex = filtro_negocio(ex)
    ex = ex.loc[ex["ano"] == ANO_ALVO].copy()
    ex["vlr_liquidado"] = pd.to_numeric(
        ex["vlr_liquidado"], errors="coerce").fillna(0.0)

    # RP Não Processado (liq) no grão7
    rpnp7 = load_rp_np_liq_grain7()
    key7 = ["ano", "uo_cod", "acao_cod", "grupo_cod",
            "iag_cod", "fonte_cod", "ipu_cod"]
    ex = ex.merge(rpnp7, on=key7, how="left")
    ex["liq_np"] = ex["liq_np"].fillna(0.0)

    # Liquidado 2026 consolidado
    ex["liquidado_2026"] = ex["vlr_liquidado"] + ex["liq_np"]

    # Agregar por detalhe (para aplicar regras por EI/obra)
    g = ["ano", "uo_cod", "acao_cod", "elemento_item_cod",
         "num_obra", "fonte_cod", "ipu_cod"]
    det = ex.groupby(g, as_index=False)["liquidado_2026"].sum()
    return det


def map_intervencoes(det: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica regra geral (plano) + regras específicas.
    O arquivo do plano está em data-raw e, no seu datapackage, tem encoding cp1252.
    """
    p_plano = os.path.join(
        "data-raw", "propag_investimentos_intervencoes_plano_2026.csv")
    # Leitura robusta (fareja sep e encodings). O datapackage indica cp1252. [1](https://cecad365-my.sharepoint.com/personal/m752868_ca_mg_gov_br/Documents/Arquivos%20de%20Microsoft%20Copilot%20Chat/datapackage_classificadores_auxiliares.json)
    plano = read_csv_smart(p_plano, encodings=("cp1252", "utf-8-sig", "utf-8"))
    keep = [c for c in ["ano", "uo_cod", "acao_cod",
                        "intervencao_cod"] if c in plano.columns]
    if not keep:
        raise ValueError("Arquivo de plano de intervenções não tem colunas esperadas: "
                         "'ano','uo_cod','acao_cod','intervencao_cod'.")
    plano = plano[keep].drop_duplicates()

    df = det.merge(plano, on=["ano", "uo_cod", "acao_cod"], how="left")

    # Regras específicas (override) conforme solicitado
    # 1) uo=1251 & acao=4365: EI 5201 -> 125102; demais EI -> 125101
    m1251 = (df["uo_cod"].eq(1251)) & (df["acao_cod"].eq(4365))
    df.loc[m1251 & df["elemento_item_cod"].eq(
        5201), "intervencao_cod"] = 125102
    df.loc[m1251 & ~df["elemento_item_cod"].eq(
        5201), "intervencao_cod"] = df.loc[m1251 & ~df["elemento_item_cod"].eq(5201), "intervencao_cod"].fillna(125101)

    # 2) uo=1301 & acao=1037 & num_obra: mapeamentos informados
    m1301 = (df["uo_cod"].eq(1301)) & (df["acao_cod"].eq(1037))
    df.loc[m1301 & df["num_obra"].eq(12221), "intervencao_cod"] = 130108
    # você indicou também 130110/130111
    df.loc[m1301 & df["num_obra"].eq(12507), "intervencao_cod"] = 130112
    df.loc[m1301 & df["num_obra"].eq(8025),  "intervencao_cod"] = 130107
    df.loc[m1301 & df["num_obra"].eq(12507), "intervencao_cod"] = 130110
    df.loc[m1301 & df["num_obra"].eq(12507), "intervencao_cod"] = 130111

    return df


def join_limite_intervencao(df_int: pd.DataFrame) -> pd.DataFrame:
    """
    Traz limite por intervenção a partir do CSV de limites (data-raw).
    Se faltar 'intervencao_cod' na planilha de limites, herdamos do plano.
    """
    p_lim = os.path.join("data-raw", "propag_investimentos_limite_2026.csv")
    lim = read_csv_smart(p_lim, encodings=(
        "utf-8-sig", "utf-8", "cp1252"), seps=(None, ";", "\t", ","))

    # Se o limite não trouxer 'intervencao_cod', herdamos do plano
    if "intervencao_cod" not in lim.columns:
        p_plano = os.path.join(
            "data-raw", "propag_investimentos_intervencoes_plano_2026.csv")
        plano = read_csv_smart(p_plano, encodings=(
            "cp1252", "utf-8-sig", "utf-8"))
        plano = plano[["ano", "uo_cod", "acao_cod",
                       "intervencao_cod"]].drop_duplicates()
        lim = lim.merge(plano, on=["ano", "uo_cod", "acao_cod"], how="left")

    need = ["ano", "uo_cod", "acao_cod", "intervencao_cod",
            "fonte_cod", "ipu_cod", "limite_propag"]
    for c in need:
        if c not in lim.columns:
            lim[c] = pd.NA

    for c in ["ano", "uo_cod", "acao_cod", "intervencao_cod", "fonte_cod", "ipu_cod"]:
        lim[c] = pd.to_numeric(lim[c], errors="coerce")
    lim["limite_propag"] = pd.to_numeric(
        lim["limite_propag"], errors="coerce").fillna(0.0)

    lim = filtro_negocio(lim)
    lim = lim.loc[lim["ano"] == ANO_ALVO]
    g = ["ano", "uo_cod", "acao_cod", "intervencao_cod", "fonte_cod", "ipu_cod"]
    lim_int = lim.groupby(g, as_index=False)["limite_propag"].sum()

    key = ["ano", "uo_cod", "acao_cod",
           "intervencao_cod", "fonte_cod", "ipu_cod"]
    return df_int.merge(lim_int, on=key, how="left")

# ---------------------------
# Orquestração
# ---------------------------


def build_table():
    det = load_exec_detalhado()
    df_int = map_intervencoes(det)
    df = join_limite_intervencao(df_int)
    df["saldo_limite"] = df["limite_propag"].fillna(
        0.0) - df["liquidado_2026"].fillna(0.0)

    cols = ["ano", "uo_cod", "acao_cod", "intervencao_cod", "fonte_cod", "ipu_cod",
            "liquidado_2026", "limite_propag", "saldo_limite"]
    df = df[cols].sort_values(
        ["ano", "uo_cod", "acao_cod", "intervencao_cod"], kind="stable")
    return df


def main():
    out = os.path.join(OUT_DIR, "tbl_pagina2_intervencao_2026.csv")
    df = build_table()
    df.to_csv(out, index=False, encoding="utf-8")
    print("Salvo:", out, "| Registros:", len(df))


if __name__ == "__main__":
    main()
