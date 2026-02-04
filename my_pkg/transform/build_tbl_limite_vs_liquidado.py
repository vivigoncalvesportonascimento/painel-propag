# my_pkg/transform/build_tbl_limite_vs_liquidado.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import hashlib
import pandas as pd

DATA_RAW = "data-raw"
DATA_DIR = "data"
OUT_DIR = "data-processed"
os.makedirs(OUT_DIR, exist_ok=True)

ANO_ALVO = 2026


def aplica_filtro_negocio(df: pd.DataFrame) -> pd.DataFrame:
    if "ipu_cod" not in df.columns:
        df = df.assign(ipu_cod=pd.NA)
    return df.loc[(df["fonte_cod"] == 89) | (df["ipu_cod"] == 0)].copy()


def parse_moeda_series(s: pd.Series) -> pd.Series:
    if s.dtype in ("float64", "int64"):
        return s.astype(float)
    s = s.astype(str).str.replace(r"[^0-9,.\-]", "", regex=True)
    s = s.str.replace(r"\.", "", regex=True).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def make_sk_link(ano: pd.Series, uo: pd.Series, fonte: pd.Series, ipu: pd.Series) -> pd.Series:
    key = (ano.astype(str) + "|" + uo.astype(str) + "|" +
           fonte.astype(str) + "|" + ipu.astype(str))
    return key.apply(lambda x: hashlib.sha1(x.encode("utf-8")).hexdigest())


def load_limite_propag_2026() -> pd.DataFrame:
    import os
    path = os.path.join(DATA_RAW, "propag_investimentos_limite_2026.csv")

    # lê farejando o separador (',' ou ';') e aceita BOM/UTF-8
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")

    # garantias mínimas
    cols_needed = ["ano", "uo_cod", "uo_sigla",
                   "fonte_cod", "ipu_cod", "limite_propag"]
    missing = [c for c in cols_needed if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colunas ausentes em limites: {missing}\nColunas lidas: {list(df.columns)}\nArquivo: {path}"
        )

    # filtro de negócio (fonte=89 ou ipu=0) e ano alvo
    df = aplica_filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO].copy()

    # converter limite (texto) para número
    df["limite_propag"] = parse_moeda_series(df["limite_propag"])

    # agrega no grão (ano, uo_cod, fonte_cod, ipu_cod)
    grp = (df.groupby(["ano", "uo_cod", "fonte_cod", "ipu_cod"], as_index=False, dropna=False)
           ["limite_propag"].sum())
    return grp


def load_execucao_2026() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "execucao.csv.gz")
    usecols = ["ano", "uo_cod", "fonte_cod", "ipu_cod", "vlr_liquidado"]
    df = pd.read_csv(path, compression="gzip",
                     usecols=usecols, encoding="utf-8")
    df = aplica_filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO].copy()
    grp = df.groupby(["ano", "uo_cod", "fonte_cod", "ipu_cod"],
                     as_index=False, dropna=False)["vlr_liquidado"].sum()
    return grp


def load_restos_rpnp_liquidado_2026() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "restos_pagar.csv.gz")
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
    path = os.path.join(DATA_DIR, "uo.csv")
    usecols = ["ano", "uo_cod", "uo_sigla"]
    df = pd.read_csv(path, usecols=usecols, encoding="utf-8")
    return df.drop_duplicates(subset=["ano", "uo_cod"])


def load_dim_fonte() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "fonte_recurso.csv")
    usecols = ["ano", "fonte_cod", "fonte_desc"]
    if not os.path.exists(path):
        return pd.DataFrame(columns=usecols)
    df = pd.read_csv(path, usecols=usecols, encoding="utf-8")
    return df.drop_duplicates(subset=["ano", "fonte_cod"])


def build_link_table(df_lim: pd.DataFrame, df_exec: pd.DataFrame, df_rpnp: pd.DataFrame) -> pd.DataFrame:
    keys_cols = ["ano", "uo_cod", "fonte_cod", "ipu_cod"]
    lk = pd.concat([df_lim[keys_cols], df_exec[keys_cols],
                   df_rpnp[keys_cols]], ignore_index=True)
    lk = lk.drop_duplicates().reset_index(drop=True)
    lk["sk_link"] = make_sk_link(
        lk["ano"], lk["uo_cod"], lk["fonte_cod"], lk["ipu_cod"])
    return lk


def build_table() -> pd.DataFrame:
    df_lim = load_limite_propag_2026()
    df_exec = load_execucao_2026()
    df_rpnp = load_restos_rpnp_liquidado_2026()

    link = build_link_table(df_lim, df_exec, df_rpnp)

    tbl = (link
           .merge(df_lim,  on=["ano", "uo_cod", "fonte_cod", "ipu_cod"], how="left")
           .merge(df_exec, on=["ano", "uo_cod", "fonte_cod", "ipu_cod"], how="left")
           .merge(df_rpnp, on=["ano", "uo_cod", "fonte_cod", "ipu_cod"], how="left"))

    for col in ["limite_propag", "vlr_liquidado", "vlr_despesa_liquidada_rpnp"]:
        if col in tbl.columns:
            tbl[col] = tbl[col].fillna(0.0)

    tbl["liquidado_2026"] = tbl["vlr_liquidado"] + \
        tbl["vlr_despesa_liquidada_rpnp"]
    tbl["saldo_limite"] = tbl["limite_propag"] - tbl["liquidado_2026"]

    dim_uo = load_dim_uo()
    tbl = tbl.merge(dim_uo, on=["ano", "uo_cod"], how="left")

    dim_fonte = load_dim_fonte()
    if not dim_fonte.empty:
        tbl = tbl.merge(dim_fonte, on=["ano", "fonte_cod"], how="left")

    cols_final = ["ano", "uo_cod", "uo_sigla", "fonte_cod", "ipu_cod",
                  "limite_propag", "liquidado_2026", "saldo_limite"]
    if "fonte_desc" in tbl.columns:
        cols_final.insert(4, "fonte_desc")

    tbl_final = tbl[cols_final].copy()
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
    sort_cols = ["Ano", "UO cod", "Fonte", "IPU"]
    tbl_final = tbl_final.sort_values(
        sort_cols, kind="stable").reset_index(drop=True)
    return tbl_final


def main():
    df = build_table()
    out_parquet = os.path.join(OUT_DIR, "tbl_limite_liquidado_2026.parquet")
    out_csv = os.path.join(OUT_DIR, "tbl_limite_liquidado_2026.csv")
    df.to_parquet(out_parquet, index=False)
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print("Registros:", len(df))
    print("Total Limite:", df["Limite Propag 2026"].sum())
    print("Total Liquidado 2026:", df["Liquidado 2026"].sum())
    print("Total Saldo:", df["Saldo de limite"].sum())


if __name__ == "__main__":
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", 20)
    main()
