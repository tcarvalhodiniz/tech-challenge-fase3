"""
Aplicação estratégica: do modelo para a decisão de política pública.

A avaliação mostrou que o modelo erra bastante em cada aluno e acerta bem quando
as predições são agregadas por município, com correlação de 0,83. Este passo parte
daí e trabalha no nível em que o modelo é confiável.

Responde três perguntas do desafio: quais municípios apresentam maior risco, quais
territórios têm padrões semelhantes e quais tendem a não atingir a meta de 2030.

Uso:
    GOOGLE_APPLICATION_CREDENTIALS=chave.json python -m src.modeling.aplicacao
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from config import settings
from src.modeling.pipeline import carregar

ANO_ALVO = 2024
ANO_META = 2030
N_PERFIS = 4

# Municípios com poucos alunos avaliados produzem taxas instáveis; entram no
# resultado mas ficam marcados, para que a priorização não se apoie em ruído.
MINIMO_ALUNOS = 30

PALETA = {"risco": "#C44E52", "ok": "#4C72B0", "ref": "#8C8C8C", "alerta": "#DD8452"}


def _salvar(fig, nome):
    caminho = os.path.join(settings.PATHS["images"], nome)
    fig.savefig(caminho, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def escore_por_municipio(pipe, X, y, grupos) -> pd.DataFrame:
    """
    Taxa prevista de alfabetização em cada município.

    A média das probabilidades individuais estima a proporção esperada de crianças
    alfabetizadas, que é a grandeza sobre a qual a decisão de política é tomada.
    """
    prob = pipe.predict_proba(X)[:, 1]
    d = pd.DataFrame({
        "id_municipio": grupos.values,
        "sigla_uf": X["sigla_uf"].values,
        "regiao": X["regiao"].values,
        "prob": prob,
        "real": y.values,
        "taxa_anterior": X["taxa_municipio_ant"].values,
        "ideb": X["ideb_municipio"].values,
        "pib_per_capita_log": X["log_pib_per_capita_municipio"].values,
        "populacao_log": X["log_populacao_municipio"].values,
    })

    mun = d.groupby("id_municipio").agg(
        sigla_uf=("sigla_uf", "first"),
        regiao=("regiao", "first"),
        alunos=("real", "size"),
        taxa_prevista=("prob", "mean"),
        taxa_observada=("real", "mean"),
        taxa_anterior=("taxa_anterior", "first"),
        ideb=("ideb", "first"),
        pib_per_capita_log=("pib_per_capita_log", "first"),
        populacao_log=("populacao_log", "first"),
    ).reset_index()

    mun[["taxa_prevista", "taxa_observada"]] *= 100
    mun["amostra_pequena"] = mun["alunos"] < MINIMO_ALUNOS
    return mun


def carregar_trajetoria(client=None) -> pd.DataFrame:
    """Realizado de 2023 e 2024 e a meta de 2030, da Gold da Fase 2."""
    from google.cloud import bigquery

    client = client or bigquery.Client(project=settings.BILLING_PROJECT_ID)
    sql = f"""
    WITH r AS (
      SELECT id_municipio, ano_ref, AVG(valor) valor
      FROM `{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.evolucao_municipio`
      WHERE tipo = 'realizado' GROUP BY id_municipio, ano_ref
    ),
    m AS (
      SELECT id_municipio, AVG(valor) meta_2030
      FROM `{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.evolucao_municipio`
      WHERE tipo = 'meta' AND ano_ref = {ANO_META} GROUP BY id_municipio
    )
    SELECT m.id_municipio, m.meta_2030,
           MAX(IF(r.ano_ref = 2023, r.valor, NULL)) realizado_2023,
           MAX(IF(r.ano_ref = 2024, r.valor, NULL)) realizado_2024
    FROM m LEFT JOIN r USING (id_municipio)
    GROUP BY m.id_municipio, m.meta_2030
    """
    return client.query(sql).to_dataframe()


def ritmo_ate_2030(mun: pd.DataFrame, trajetoria: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Compara o ritmo de avanço com o exigido pela meta, no agregado.

    A tentação seria classificar cada município como no ritmo ou em retrocesso.
    Isso não se sustenta: o município mediano teve 112 alunos avaliados, o que dá
    um desvio amostral de cerca de 4,6 pontos na taxa, e a variação observada entre
    2023 e 2024 tem desvio de 16 pontos, com 18% dos municípios oscilando mais de
    10 pontos em um ano. Boa parte dessa variação é sorteio, não mudança
    educacional, e dois pontos no tempo não separam uma coisa da outra.

    O agregado nacional é estável porque a amostragem se cancela entre milhares de
    municípios, então é nele que a comparação de ritmos faz sentido.
    """
    d = mun.merge(trajetoria, on="id_municipio", how="left")
    com_serie = d.dropna(subset=["realizado_2023", "realizado_2024", "meta_2030"])

    anos = ANO_META - ANO_ALVO
    observado = float((com_serie["realizado_2024"] - com_serie["realizado_2023"]).mean())
    atual = float(com_serie["realizado_2024"].mean())
    meta = float(com_serie["meta_2030"].mean())
    necessario = (meta - atual) / anos

    d["distancia_meta_2030"] = d["meta_2030"] - d["realizado_2024"]

    resumo = {
        "municipios_com_serie": len(com_serie),
        "taxa_media_2024": round(atual, 2),
        "meta_media_2030": round(meta, 2),
        "ritmo_necessario_pp_ano": round(necessario, 2),
        "ritmo_observado_pp_ano": round(observado, 2),
        "defasagem_pp_ano": round(observado - necessario, 2),
        "desvio_da_variacao_municipal_pp": round(
            float((com_serie["realizado_2024"] - com_serie["realizado_2023"]).std()), 2),
        "ruido_amostral_estimado_pp": round(
            float(100 * np.sqrt(0.6 * 0.4 / com_serie["alunos"].median())), 2),
        "ja_atingiram_a_meta": int((com_serie["realizado_2024"] >= com_serie["meta_2030"]).sum()),
    }
    return d, resumo


def agrupar_perfis(mun: pd.DataFrame, n=N_PERFIS, seed=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Agrupa municípios com perfil socioeducacional parecido.

    Responde à pergunta sobre territórios semelhantes sem usar o desfecho: o
    agrupamento vê contexto (histórico, IDEB, renda, porte) e os perfis resultantes
    são descritos depois pela taxa que apresentam.
    """
    seed = settings.SEED if seed is None else seed
    colunas = ["taxa_anterior", "ideb", "pib_per_capita_log", "populacao_log"]

    modelo = Pipeline([
        ("imputacao", SimpleImputer(strategy="median")),
        ("escala", StandardScaler()),
        ("kmeans", KMeans(n_clusters=n, random_state=seed, n_init=10)),
    ])
    mun = mun.copy()
    mun["perfil"] = modelo.fit_predict(mun[colunas])

    resumo = mun.groupby("perfil").agg(
        municipios=("id_municipio", "size"),
        taxa_prevista=("taxa_prevista", "mean"),
        taxa_anterior=("taxa_anterior", "mean"),
        ideb=("ideb", "mean"),
        populacao=("populacao_log", lambda s: np.expm1(s.mean())),
        pib_per_capita=("pib_per_capita_log", lambda s: np.expm1(s.mean())),
    ).round(2).reset_index()

    # Os grupos não se ordenam numa escala única: diferem em porte, renda e
    # desempenho ao mesmo tempo. Nomear pelo ranking da taxa esconderia isso, e
    # esconderia justamente o par mais informativo, que são os dois grupos de
    # mesma renda e desempenhos muito distantes. O rótulo descreve o perfil.
    def rotular(r):
        grande = r["populacao"] > 30_000
        rico = r["pib_per_capita"] > 30_000
        if grande:
            return "urbano de grande porte"
        if rico:
            return "pequeno e próspero"
        return "pequeno de baixa renda, bom desempenho" if r["taxa_prevista"] >= 60 \
            else "pequeno de baixa renda, desempenho crítico"

    mapa = {r["perfil"]: rotular(r) for _, r in resumo.iterrows()}
    mun["perfil_nome"] = mun["perfil"].map(mapa)
    resumo["perfil_nome"] = resumo["perfil"].map(mapa)

    return mun, resumo.sort_values("taxa_prevista").reset_index(drop=True)


def fig_risco(mun: pd.DataFrame):
    """Distribuição da taxa prevista, destacando o quinto mais crítico."""
    corte = mun["taxa_prevista"].quantile(0.20)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.hist(mun.loc[mun["taxa_prevista"] <= corte, "taxa_prevista"], bins=30,
            color=PALETA["risco"], label=f"quinto mais crítico (até {corte:.1f}%)")
    ax.hist(mun.loc[mun["taxa_prevista"] > corte, "taxa_prevista"], bins=50,
            color=PALETA["ok"], label="demais municípios")
    ax.set_xlabel("Taxa de alfabetização prevista (%)")
    ax.set_ylabel("Municípios")
    ax.set_title("Distribuição do risco entre os municípios", fontsize=12, pad=10)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "15_risco_municipios.png")


def fig_perfis(resumo: pd.DataFrame):
    """Perfis identificados pelo agrupamento."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    cores = [PALETA["risco"], PALETA["alerta"], PALETA["ref"], PALETA["ok"]]

    ax1.bar(resumo["perfil_nome"], resumo["taxa_prevista"], color=cores[:len(resumo)])
    ax1.set_ylabel("Taxa prevista média (%)")
    ax1.set_title("Desempenho esperado por perfil", fontsize=11)

    ax2.bar(resumo["perfil_nome"], resumo["municipios"], color=cores[:len(resumo)])
    ax2.set_ylabel("Municípios")
    ax2.set_title("Tamanho de cada perfil", fontsize=11)

    for ax in (ax1, ax2):
        ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "16_perfis_municipios.png")


def main():
    from google.cloud import bigquery

    X, y, grupos = carregar()
    pipe = joblib.load(os.path.join(settings.PATHS["models"], "modelo.joblib"))
    client = bigquery.Client(project=settings.BILLING_PROJECT_ID)

    mun = escore_por_municipio(pipe, X, y, grupos)
    print(f"{len(mun):,} municípios com predição")

    mun, perfis = agrupar_perfis(mun)
    print(f"\nperfis identificados:")
    for _, r in perfis.iterrows():
        print(f"  {r['perfil_nome']:15s} {int(r['municipios']):>5,} municípios  "
              f"taxa prevista {r['taxa_prevista']:.1f}%  IDEB {r['ideb']:.2f}  "
              f"pop. média {r['populacao']:,.0f}")

    d, ritmo = ritmo_ate_2030(mun, carregar_trajetoria(client))
    print(f"\nritmo até a meta de {ANO_META} ({ritmo['municipios_com_serie']:,} municípios com série):")
    print(f"  taxa média em 2024 .............. {ritmo['taxa_media_2024']:.1f}%")
    print(f"  meta média para 2030 ............ {ritmo['meta_media_2030']:.1f}%")
    print(f"  ritmo necessário ................ {ritmo['ritmo_necessario_pp_ano']:.2f} p.p./ano")
    print(f"  ritmo observado (2023 a 2024) ... {ritmo['ritmo_observado_pp_ano']:.2f} p.p./ano")
    print(f"  defasagem ....................... {ritmo['defasagem_pp_ano']:+.2f} p.p./ano")
    print(f"  (variação municipal tem desvio de {ritmo['desvio_da_variacao_municipal_pp']:.1f} p.p. "
          f"contra ruído amostral de ~{ritmo['ruido_amostral_estimado_pp']:.1f} p.p.:")
    print(f"   por isso a leitura é agregada, não por município)")

    corte = d["taxa_prevista"].quantile(0.20)
    criticos = d[(d["taxa_prevista"] <= corte) & (~d["amostra_pequena"])]
    print(f"\nquinto mais crítico: {len(criticos):,} municípios (taxa prevista até {corte:.1f}%)")
    print(criticos["regiao"].value_counts().to_string())

    figuras = [fig_risco(d), fig_perfis(perfis)]
    print("\nfiguras:")
    for f in figuras:
        print("  ", os.path.basename(f))

    saida = os.path.join(settings.PATHS["processed"], "risco_municipio.parquet")
    d.to_parquet(saida, index=False)
    print(f"\ngravado: {saida}")

    relatorio = os.path.join(settings.PATHS["reports"], "aplicacao.json")
    with open(relatorio, "w", encoding="utf-8") as f:
        json.dump({
            "municipios": len(d),
            "perfis": perfis.to_dict(orient="records"),
            "ritmo_2030": ritmo,
            "corte_quinto_critico": round(float(corte), 2),
            "criticos_por_regiao": criticos["regiao"].value_counts().to_dict(),
        }, f, indent=2, ensure_ascii=False)
    print(f"relatório: {relatorio}")


if __name__ == "__main__":
    main()
