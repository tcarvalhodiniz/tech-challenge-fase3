"""
Enriquecimento socioeconômico por município.

O objetivo do desafio pede variáveis educacionais, territoriais e
socioeconômicas. A Gold da Fase 2 cobre as duas primeiras; as socioeconômicas
vêm de outras bases públicas do mesmo BigQuery, cruzadas pelo `id_municipio`,
que é o código IBGE e o único identificador estável desta base.

Todas as fontes são anteriores ao ano modelado. Isso não é detalhe: repetir a
janela do alvo reintroduziria exatamente o vazamento de agregado corrigido no
passo anterior.

Uso:
    GOOGLE_APPLICATION_CREDENTIALS=chave.json python -m src.preprocessing.enriquecimento
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import numpy as np
import pandas as pd
from google.cloud import bigquery

from config import settings

# Ano de referência de cada fonte, escolhido pela disponibilidade real na data da
# predição. O IDEB é bienal e 2023 é o ciclo anterior ao alvo. O PIB municipal do
# IBGE sai com cerca de dois anos de defasagem, então 2023 não estaria publicado
# antes da avaliação de 2024.
ANO_IDEB = 2023
ANO_PIB = 2022
ANO_POPULACAO = 2023


def sql_ideb() -> str:
    """
    IDEB dos anos iniciais, que abrangem o 2º ano avaliado.

    Mede outra coorte (a prova do IDEB é aplicada no 5º ano) e outro ciclo, então
    funciona como indicador defasado da qualidade do ensino no município, não como
    medida do desfecho que se quer prever.
    """
    return f"""
    SELECT
        id_municipio,
        ideb                        AS ideb_municipio,
        taxa_aprovacao              AS aprovacao_municipio,
        nota_saeb_media_padronizada AS saeb_padronizado_municipio
    FROM `basedosdados.br_inep_ideb.municipio`
    WHERE ano = {ANO_IDEB}
      AND ensino = 'fundamental'
      AND anos_escolares = 'iniciais (1-5)'
      AND rede = 'publica'
    """


def sql_economia() -> str:
    """PIB per capita e porte populacional do município."""
    return f"""
    WITH pib AS (
        SELECT id_municipio, pib
        FROM `basedosdados.br_ibge_pib.municipio`
        WHERE ano = {ANO_PIB}
    ),
    pop AS (
        SELECT id_municipio, populacao
        FROM `basedosdados.br_ibge_populacao.municipio`
        WHERE ano = {ANO_POPULACAO}
    )
    SELECT
        pop.id_municipio,
        pop.populacao                       AS populacao_municipio,
        SAFE_DIVIDE(pib.pib, pop.populacao) AS pib_per_capita_municipio
    FROM pop
    LEFT JOIN pib USING (id_municipio)
    """


def custo(client, *consultas) -> dict:
    """Estima quanto as consultas varrem antes de executá-las."""
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    total = sum(client.query(q, job_config=cfg).total_bytes_processed for q in consultas)
    gb = total / 1e9
    return {"gb_processados": round(gb, 4), "custo_usd": round(gb / 1000 * 6.25, 5)}


def buscar(client=None) -> pd.DataFrame:
    """Uma linha por município, com os indicadores externos."""
    client = client or bigquery.Client(project=settings.BILLING_PROJECT_ID)

    ideb = client.query(sql_ideb()).to_dataframe()
    economia = client.query(sql_economia()).to_dataframe()

    externo = economia.merge(ideb, on="id_municipio", how="outer")

    # população e PIB per capita são grandezas multiplicativas, com cauda longa:
    # o log aproxima a distribuição da normal e evita que capitais dominem a escala.
    # A transformação não tem parâmetro estimado, então não vaza entre partições.
    for col in ["populacao_municipio", "pib_per_capita_municipio"]:
        externo[f"log_{col}"] = np.log1p(externo[col])

    return externo.drop(columns=["populacao_municipio", "pib_per_capita_municipio"])


def main():
    client = bigquery.Client(project=settings.BILLING_PROJECT_ID)

    c = custo(client, sql_ideb(), sql_economia())
    print(f"varredura estimada: {c['gb_processados']} GB (US$ {c['custo_usd']})")

    externo = buscar(client)
    print(f"\n{len(externo):,} municípios | {externo.shape[1] - 1} indicadores")
    print("\ncobertura:")
    for col in externo.columns:
        if col == "id_municipio":
            continue
        print(f"  {col:34s} {100 * externo[col].notna().mean():6.2f}%")

    destino = os.path.join(settings.PATHS["processed"], "externo_municipio.parquet")
    externo.to_parquet(destino, index=False)
    print(f"\ngravado: {destino}")

    relatorio = os.path.join(settings.PATHS["reports"], "enriquecimento.json")
    with open(relatorio, "w", encoding="utf-8") as f:
        json.dump({
            "fontes": {
                "ideb": f"basedosdados.br_inep_ideb.municipio ({ANO_IDEB}, iniciais)",
                "pib": f"basedosdados.br_ibge_pib.municipio ({ANO_PIB})",
                "populacao": f"basedosdados.br_ibge_populacao.municipio ({ANO_POPULACAO})",
            },
            "finops": c,
            "municipios": len(externo),
            "cobertura": {
                c_: round(100 * externo[c_].notna().mean(), 2)
                for c_ in externo.columns if c_ != "id_municipio"
            },
        }, f, indent=2, ensure_ascii=False)
    print(f"relatório: {relatorio}")


if __name__ == "__main__":
    main()
