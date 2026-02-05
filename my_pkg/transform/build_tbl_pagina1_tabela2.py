# my_pkg/transform/build_tbl_pagina1_tabela2.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import glob
import hashlib
import pandas as pd

ANO_ALVO = 2026
OUT_DIR = "data-processed"
os.makedirs(OUT_DIR, exist_ok=True)

DATA_DIRS = [
    os.path.join("datapackages", "siafi-2026", "data"),
    os.path.join("datapackages", "aux-classificadores", "data"),
]


def find_existing(*names: str) -> str:
    for d in DATA_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    for n in names:
        for m in glob.glob(os.path.join("datapackages", "**", "data", n), recursive=True):
            if os.path.exists(m):
                return m
    raise FileNotFoundError(names)


def filtro_negocio(df: pd.DataFrame) -> pd.DataFrame:
    if "fonte_cod" not in df.columns:
        return df.iloc[0:0].copy()
    if "ipu_cod" not in df.columns:
        df = df.assign(ipu_cod=pd.NA)
    return df.loc[(df["fonte_cod"] == 89) | (df["ipu_cod"] == 0)].copy()


def mk_sk7(d: pd.DataFrame) -> pd.Series:
    s = (d["ano"].astype(str)+"\n"+d["uo_cod"].astype(str)+"\n"+d["acao_cod"].astype(str)+"\n" +
         d["grupo_cod"].astype(str)+"\n"+d["iag_cod"].astype(str)+"\n"+d["fonte_cod"].astype(str)+"\n" +
         d["ipu_cod"].astype(str))
    return s.apply(lambda x: hashlib.sha1(x.encode("utf-8")).hexdigest())

# -------- dimensões (aux-classificadores) --------


def dim_uo():
    p = find_existing("uo.csv")
    d = pd.read_csv(p, encoding="utf-8",
                    usecols=["ano", "uo_cod", "uo_sigla"]).drop_duplicates(["ano", "uo_cod"])
    return d


def dim_acao():
    try:
        p = find_existing("acao.csv")
        d = pd.read_csv(
            p, encoding="utf-8", usecols=["ano", "acao_cod", "acao_desc"]).drop_duplicates()
        return d
    except Exception:
        p = find_existing("funcional_programatica.csv")
        d = pd.read_csv(p, encoding="utf-8")
        d = d.rename(columns={"acao_desc": "acao_desc",
                     "acao_cod": "acao_cod", "ano": "ano"})
        return d[["ano", "acao_cod", "acao_desc"]].drop_duplicates()


def dim_fonte():
    try:
        p = find_existing("fonte_recurso.csv")
        d = pd.read_csv(p, encoding="utf-8", usecols=[
                        "ano", "fonte_cod", "fonte_desc"]).drop_duplicates(["ano", "fonte_cod"])
        return d
    except Exception:
        return pd.DataFrame(columns=["ano", "fonte_cod", "fonte_desc"])

# -------- fatos --------


def load_limites():
    p = os.path.join("data-raw", "propag_investimentos_limite_2026.csv")
    df = pd.read_csv(p, sep=None, engine="python", encoding="utf-8")
    need = ["ano", "uo_cod", "acao_cod", "grupo_cod",
            "iag_cod", "fonte_cod", "ipu_cod", "limite_propag"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"Limites: coluna ausente: {c}")
    for c in ["ano", "uo_cod", "acao_cod", "grupo_cod", "iag_cod", "fonte_cod", "ipu_cod"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["limite_propag"] = pd.to_numeric(
        df["limite_propag"], errors="coerce").fillna(0.0)
    df = filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO]
    g = ["ano", "uo_cod", "acao_cod", "grupo_cod",
         "iag_cod", "fonte_cod", "ipu_cod"]
    return df.groupby(g, as_index=False)["limite_propag"].sum()


def load_execucao():
    p = find_existing("execucao.csv.gz")
    use = ["ano", "uo_cod", "acao_cod", "grupo_cod", "iag_cod", "fonte_cod", "ipu_cod",
           "vlr_empenhado", "vlr_liquidado", "vlr_pago_orcamentario"]
    df = pd.read_csv(p, compression="gzip", encoding="utf-8", usecols=use)
    df = filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO]
    for c in ["vlr_empenhado", "vlr_liquidado", "vlr_pago_orcamentario"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    g = ["ano", "uo_cod", "acao_cod", "grupo_cod",
         "iag_cod", "fonte_cod", "ipu_cod"]
    return df.groupby(g, as_index=False)[["vlr_empenhado", "vlr_liquidado", "vlr_pago_orcamentario"]].sum()


def load_rp():
    p = find_existing("restos_pagar.csv.gz")
    df = pd.read_csv(p, compression="gzip", encoding="utf-8")
    df = filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO]
    g = ["ano", "uo_cod", "acao_cod", "grupo_cod",
         "iag_cod", "fonte_cod", "ipu_cod"]

    def to_num(c): return pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    # Fórmulas segundo suas regras
    df["insc_proc"] = to_num("vlr_inscrito_rpp")
    df["canc_proc"] = to_num("vlr_cancelado_rpp") + \
        to_num("vlr_desconto_rpp") - to_num("vlr_restabelecido_rpp")
    df["pago_proc"] = to_num("vlr_pago_rpp") - to_num("vlr_anulacao_pagamento_rpp") + \
        to_num("vlr_retencao_rpp") - to_num("vlr_anulacao_retencao_rpp")
    df["saldo_proc"] = to_num("vlr_saldo_rpp")
    df["insc_np"] = to_num("vlr_inscrito_rpnp")
    df["canc_np"] = to_num("vlr_cancelado_rpnp") - \
        to_num("vlr_restabelecido_rpnp")
    df["liq_np"] = to_num("vlr_despesa_liquidada_rpnp")
    df["saldo_np"] = to_num("vlr_saldo_rpnp")
    df["pago_np"] = to_num("vlr_saldo_rpp") + to_num(
        "vlr_despesa_liquidada_rpnp") - to_num("vlr_despesa_liquidada_pagar")

    agg = df.groupby(g, as_index=False)[["insc_proc", "canc_proc", "pago_proc",
                                         "saldo_proc", "insc_np", "canc_np", "liq_np", "saldo_np", "pago_np"]].sum()
    return agg


def load_credito():
    p = find_existing("credito.csv.gz")
    use = ["ano", "uo_cod", "acao_cod", "grupo_cod", "iag_cod", "fonte_cod",
           "ipu_cod", "vlr_credito_inicial", "vlr_credito_autorizado"]
    df = pd.read_csv(p, compression="gzip", encoding="utf-8", usecols=use)
    df = filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO]
    for c in ["vlr_credito_inicial", "vlr_credito_autorizado"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    g = ["ano", "uo_cod", "acao_cod", "grupo_cod",
         "iag_cod", "fonte_cod", "ipu_cod"]
    return df.groupby(g, as_index=False)[["vlr_credito_inicial", "vlr_credito_autorizado"]].sum()


def load_cota():
    p = find_existing("cota.csv.gz")
    df = pd.read_csv(p, compression="gzip", encoding="utf-8")
    df = filtro_negocio(df)
    df = df.loc[df["ano"] == ANO_ALVO]
    if "vlr_cota_aprovada" not in df.columns:
        df["vlr_cota_aprovada"] = 0.0
    df["vlr_cota_aprovada"] = pd.to_numeric(
        df["vlr_cota_aprovada"], errors="coerce").fillna(0.0)
    g = ["ano", "uo_cod", "acao_cod", "grupo_cod",
         "iag_cod", "fonte_cod", "ipu_cod"]
    return df.groupby(g, as_index=False)[["vlr_cota_aprovada"]].sum()


def build_table():
    key = ["ano", "uo_cod", "acao_cod", "grupo_cod",
           "iag_cod", "fonte_cod", "ipu_cod"]
    lim = load_limites()
    exe = load_execucao()
    rp = load_rp()
    cre = load_credito()
    cot = load_cota()

    link = pd.concat([lim[key], exe[key], rp[key], cre[key],
                     cot[key]], ignore_index=True).drop_duplicates()
    link["sk7"] = mk_sk7(link)

    tbl = (link
           .merge(lim, on=key, how="left")
           .merge(cre, on=key, how="left")
           .merge(cot, on=key, how="left")
           .merge(exe, on=key, how="left")
           .merge(rp,  on=key, how="left")
           ).fillna(0.0)

    # Métricas finais
    tbl["Liquidado_2026"] = tbl["vlr_liquidado"] + tbl["liq_np"]
    tbl["Pago_Orc_2026"] = tbl["vlr_pago_orcamentario"] + \
        tbl["pago_proc"] + tbl["pago_np"]

    # Dimensões textuais
    d_uo = dim_uo()
    d_acao = dim_acao()
    d_fonte = dim_fonte()
    tbl = (tbl.merge(d_uo,   on=["ano", "uo_cod"], how="left")
              .merge(d_acao, on=["ano", "acao_cod"], how="left")
              .merge(d_fonte, on=["ano", "fonte_cod"], how="left"))

    cols = ["ano", "uo_cod", "uo_sigla", "acao_cod", "acao_desc", "grupo_cod", "iag_cod",
            "fonte_cod", "fonte_desc", "ipu_cod",
            "limite_propag", "vlr_credito_inicial", "vlr_credito_autorizado", "vlr_cota_aprovada",
            "vlr_empenhado", "Liquidado_2026", "Pago_Orc_2026", "sk7"]
    cols = [c for c in cols if c in tbl.columns]
    tbl = tbl[cols].sort_values(
        ["ano", "uo_cod", "acao_cod", "grupo_cod", "iag_cod", "fonte_cod", "ipu_cod"], kind="stable")
    return tbl


def main():
    df = build_table()
    out = os.path.join(OUT_DIR, "tbl_pagina1_tabela2_2026.csv")
    df.to_csv(out, index=False, encoding="utf-8")
    print("Salvo:", out, "| Registros:", len(df))


if __name__ == "__main__":
    main()
