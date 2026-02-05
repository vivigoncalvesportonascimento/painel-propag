# my_pkg/transform/build_pagina2_intervencao.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import pandas as pd

ANO_ALVO = 2026
OUT_DIR = "data-processed"
os.makedirs(OUT_DIR, exist_ok=True)

DATA_SIAFI = os.path.join("datapackages", "siafi-2026", "data")


def filtro_negocio(df: pd.DataFrame) -> pd.DataFrame:
    if "fonte_cod" not in df.columns:
        return df.iloc[0:0].copy()
    if "ipu_cod" not in df.columns:
        df = df.assign(ipu_cod=pd.NA)
    return df.loc[(df["fonte_cod"] == 89) | (df["ipu_cod"] == 0)].copy()


def load_rp_np_liq_grain7() -> pd.DataFrame:
    p = os.path.join(DATA_SIAFI, "restos_pagar.csv.gz")
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
    p = os.path.join(DATA_SIAFI, "execucao.csv.gz")
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

    ex["liquidado_2026"] = ex["vlr_liquidado"] + ex["liq_np"]

    # Agregar por detalhe necessário para regras (EI/obra)
    g = ["ano", "uo_cod", "acao_cod", "elemento_item_cod",
         "num_obra", "fonte_cod", "ipu_cod"]
    det = ex.groupby(g, as_index=False)["liquidado_2026"].sum()
    return det


def map_intervencoes(det: pd.DataFrame) -> pd.DataFrame:
    # Regra geral via plano (ano+uo+acao)
    p_plano = os.path.join(
        "data-raw", "propag_investimentos_intervencoes_plano_2026.csv")
    plano = pd.read_csv(p_plano, encoding="cp1252")
    keep = [c for c in ["ano", "uo_cod", "acao_cod",
                        "intervencao_cod"] if c in plano.columns]
    plano = plano[keep].drop_duplicates()

    df = det.merge(plano, on=["ano", "uo_cod", "acao_cod"], how="left")

    # Regras específicas (override)
    # 1) uo=1251 & acao=4365
    m1251 = (df["uo_cod"].eq(1251)) & (df["acao_cod"].eq(4365))
    df.loc[m1251 & df["elemento_item_cod"].eq(
        5201), "intervencao_cod"] = 125102
    df.loc[m1251 & ~df["elemento_item_cod"].eq(
        5201), "intervencao_cod"] = df.loc[m1251 & ~df["elemento_item_cod"].eq(5201), "intervencao_cod"].fillna(125101)

    # 2) uo=1301 & acao=1037 & num_obra
    m1301 = (df["uo_cod"].eq(1301)) & (df["acao_cod"].eq(1037))
    df.loc[m1301 & df["num_obra"].eq(12221), "intervencao_cod"] = 130108
    # você listou também 130110 e 130111
    df.loc[m1301 & df["num_obra"].eq(12507), "intervencao_cod"] = 130112
    df.loc[m1301 & df["num_obra"].eq(8025),  "intervencao_cod"] = 130107
    df.loc[m1301 & df["num_obra"].eq(12507), "intervencao_cod"] = 130110
    df.loc[m1301 & df["num_obra"].eq(12507), "intervencao_cod"] = 130111

    return df


def join_limite_intervencao(df_int: pd.DataFrame) -> pd.DataFrame:
    # Limite por intervenção
    p_lim = os.path.join("data-raw", "propag_investimentos_limite_2026.csv")
    lim = pd.read_csv(p_lim, sep=None, engine="python", encoding="utf-8")

    # Se a planilha de limite não trouxer 'intervencao_cod', herdar do plano
    if "intervencao_cod" not in lim.columns:
        p_plano = os.path.join(
            "data-raw", "propag_investimentos_intervencoes_plano_2026.csv")
        plano = pd.read_csv(p_plano, encoding="cp1252")[
            ["ano", "uo_cod", "acao_cod", "intervencao_cod"]].drop_duplicates()
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
