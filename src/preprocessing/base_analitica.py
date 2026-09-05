"""
Constrói a base analítica no grão de aluno.

Junta os microdados do Alfabetiza Brasil com o contexto de município e de UF da
camada Gold da Fase 2, deriva território a partir do código IBGE e materializa
tudo em parquet.

As colunas de vazamento (`proficiencia` e companhia) **são extraídas de
propósito**: elas sustentam a evidência da análise exploratória que justifica a
exclusão. Quem as remove é a pipeline de modelagem, lendo a lista declarada em
`config.settings.COLUNAS_VAZAMENTO` — nunca uma remoção manual espalhada pelo
código.

Uso:
    GOOGLE_APPLICATION_CREDENTIALS=chave.json python -m src.preprocessing.base_analitica
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import pandas as pd
from google.cloud import bigquery

from config import settings

# Preço on-demand do BigQuery por TB varrido (mesma referência usada na Fase 2)
USD_POR_TB = 6.25

# Primeiro dígito do código IBGE do município identifica a região
REGIOES = {
    "1": "Norte",
    "2": "Nordeste",
    "3": "Sudeste",
    "4": "Sul",
    "5": "Centro-Oeste",
}

# Dois primeiros dígitos identificam a UF
UFS = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}


def sql_alunos_municipio() -> str:
    """Microdados de aluno enriquecidos com o indicador do próprio município."""
    return f"""
    SELECT
        -- identificadores: não são feature, servem para agrupar na validação
        a.id_aluno,
        a.id_escola,
        a.id_municipio,

        a.ano,

        -- atributos do aluno disponíveis antes da prova
        a.rede,
        a.serie,
        a.caderno,

        -- alvo
        SAFE_CAST(a.alfabetizado AS INT64) AS alfabetizado,

        -- vazamento: extraído para evidenciar a exclusão, nunca para treinar
        a.proficiencia,
        a.peso_aluno,
        a.presenca,
        a.preenchimento_caderno,

        -- contexto do município (Gold da Fase 2)
        g.rede_desc,
        g.taxa_realizada AS taxa_municipio,
        g.meta_ano       AS meta_municipio,
        g.gap_pp         AS gap_municipio,
        g.atingiu_meta
    FROM `{settings.BD_PROJECT}.{settings.BD_DATASET}.{settings.TABELA_MICRODADOS}` a
    LEFT JOIN `{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.indicador_municipio` g
        ON  a.id_municipio = g.id_municipio
        AND a.ano          = g.ano
        AND a.rede         = g.rede
        AND a.serie        = g.serie
    """


def sql_indicador_uf() -> str:
    """Indicador agregado por UF — tabela pequena, juntada em memória."""
    return f"""
    SELECT sigla_uf, ano, rede,
           taxa_realizada AS taxa_uf,
           meta_ano       AS meta_uf,
           gap_pp         AS gap_uf
    FROM `{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.indicador_uf`
    """


def custo_consulta(client: bigquery.Client, sql: str) -> dict:
    """Estima o custo da consulta sem executá-la (dry-run)."""
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=cfg)
    gb = job.total_bytes_processed / 1e9
    return {
        "gb_processados": round(gb, 3),
        "custo_usd": round(gb / 1000 * USD_POR_TB, 4),
    }


def derivar_territorio(df: pd.DataFrame) -> pd.DataFrame:
    """UF e região a partir do código IBGE — cobertura total, sem depender do join."""
    prefixo = df["id_municipio"].str[:2]
    df["sigla_uf"] = prefixo.map(UFS)
    df["regiao"] = df["id_municipio"].str[:1].map(REGIOES)
    return df


def construir(client: bigquery.Client) -> pd.DataFrame:
    """Executa as consultas e devolve a base analítica pronta."""
    df = client.query(sql_alunos_municipio()).to_dataframe()
    df = derivar_territorio(df)

    uf = client.query(sql_indicador_uf()).to_dataframe()
    df = df.merge(uf, on=["sigla_uf", "ano", "rede"], how="left")
    return df


def validar(df: pd.DataFrame) -> dict:
    """Confere o que a base precisa garantir antes de seguir para a modelagem."""
    total = len(df)
    alvo = df[settings.ALVO]
    resumo = {
        "linhas": total,
        "colunas": df.shape[1],
        "anos": sorted(df["ano"].unique().tolist()),
        "municipios": int(df["id_municipio"].nunique()),
        "escolas": int(df["id_escola"].nunique()),
        "alvo_nulo": int(alvo.isna().sum()),
        "alvo_positivo_pct": round(100 * alvo.mean(), 2),
        "pct_com_contexto_municipio": round(
            100 * df["taxa_municipio"].notna().mean(), 2
        ),
        "pct_com_territorio": round(100 * df["sigla_uf"].notna().mean(), 2),
    }

    # o alvo não pode faltar: sem ele a linha não serve para treino supervisionado
    if resumo["alvo_nulo"] > 0:
        raise ValueError(
            f"{resumo['alvo_nulo']} linhas sem alvo — investigar antes de prosseguir"
        )
    return resumo


def main():
    client = bigquery.Client(project=settings.BILLING_PROJECT_ID)

    custo = custo_consulta(client, sql_alunos_municipio())
    print(f"FinOps — varredura estimada: {custo['gb_processados']} GB "
          f"(US$ {custo['custo_usd']})")

    print("Consultando o BigQuery...")
    df = construir(client)

    resumo = validar(df)
    print("\nBase analítica:")
    for k, v in resumo.items():
        print(f"  {k:28s} {v}")

    os.makedirs(settings.PATHS["processed"], exist_ok=True)
    destino = os.path.join(settings.PATHS["processed"], "base_analitica.parquet")
    df.to_parquet(destino, index=False)
    tamanho_mb = os.path.getsize(destino) / 1e6
    print(f"\nGravado: {destino} ({tamanho_mb:.1f} MB)")

    # o resumo fica gravado, não só impresso: métrica que só aparece na tela
    # desaparece com a sessão e não serve para comparar execuções
    os.makedirs(settings.PATHS["reports"], exist_ok=True)
    relatorio = os.path.join(settings.PATHS["reports"], "base_analitica.json")
    with open(relatorio, "w", encoding="utf-8") as f:
        json.dump({"finops": custo, "validacao": resumo}, f, indent=2, ensure_ascii=False)
    print(f"Relatório: {relatorio}")


if __name__ == "__main__":
    main()
