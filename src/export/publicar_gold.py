"""
Publica a camada Gold desta fase no BigQuery.

A Gold da Fase 2 foi construída para acompanhamento: uma linha por município, com
meta e realizado. Esta fase precisa de outro grão e de outras variáveis, então
constrói a sua própria camada analítica ao lado da anterior, no mesmo dataset.

As tabelas da Fase 2 continuam intactas e seguem alimentando o dashboard. A
linhagem entre elas é real: `meta_municipio` vem de `indicador_municipio`.

Uso:
    GOOGLE_APPLICATION_CREDENTIALS=chave.json python -m src.export.publicar_gold
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import pandas as pd
from google.cloud import bigquery

from config import settings

TABELA = "base_modelagem"

DESCRICAO = """Base analítica no grão de aluno, pronta para modelagem supervisionada.

Construída no Tech Challenge da Fase 3 a partir dos microdados do Alfabetiza Brasil,
do contexto municipal da Gold da Fase 2 e de indicadores socioeconômicos públicos
(IDEB, PIB e população).

Cobre os alunos de 2024 com prova aplicada. Não inclui as variáveis que determinam
o alvo (proficiencia, presenca, preenchimento_caderno, peso_aluno) nem os agregados
calculados no mesmo período do desfecho (taxa_municipio, gap_municipio,
atingiu_meta, taxa_uf), que foram substituídos por versões defasadas de 2023.

Os identificadores de aluno e escola não constam: a fonte os publica como máscaras
com códigos fictícios, reatribuídas a cada edição."""

DESCRICAO_COLUNAS = {
    "id_municipio": "Código IBGE de 7 dígitos; único identificador estável da base",
    "alfabetizado": "Alvo. 1 quando a proficiência atinge o corte de 743 pontos do Saeb",
    "rede": "Rede de ensino do aluno (código da fonte)",
    "caderno": "Versão do caderno de prova aplicado",
    "sigla_uf": "UF derivada dos dois primeiros dígitos do código IBGE",
    "regiao": "Região derivada do primeiro dígito do código IBGE",
    "meta_municipio": "Meta de alfabetização do município; vem da Gold da Fase 2",
    "taxa_municipio_ant": "Taxa de alfabetização do município em 2023, defasada de propósito",
    "alunos_municipio_ant": "Alunos avaliados no município em 2023; indica a confiabilidade da taxa",
    "taxa_uf_ant": "Taxa de alfabetização da UF em 2023",
    "sem_historico_municipio": "1 quando o município não tem medição de 2023 (partida a frio)",
    "ideb_municipio": "IDEB dos anos iniciais do município em 2023",
    "aprovacao_municipio": "Taxa de aprovação dos anos iniciais em 2023",
    "saeb_padronizado_municipio": "Nota Saeb padronizada dos anos iniciais em 2023",
    "log_populacao_municipio": "Log da população do município em 2023 (IBGE)",
    "log_pib_per_capita_municipio": "Log do PIB per capita do município em 2022 (IBGE)",
}


def carregar_local() -> pd.DataFrame:
    """Base materializada pelo passo de engenharia de atributos."""
    caminho = os.path.join(settings.PATHS["processed"], "base_modelagem.parquet")
    df = pd.read_parquet(caminho)

    # Tipos anuláveis do pandas não têm equivalente direto no BigQuery. Inteiros
    # com ausência (alunos_municipio_ant é nulo nos municípios sem histórico) não
    # cabem em int64, então viram float; os demais mantêm a natureza inteira.
    for c in df.select_dtypes(include=["Float64"]).columns:
        df[c] = df[c].astype("float64")
    for c in df.select_dtypes(include=["Int64"]).columns:
        df[c] = df[c].astype("float64" if df[c].isna().any() else "int64")
    return df


def publicar(df: pd.DataFrame, client=None) -> str:
    """Grava a tabela e anexa as descrições que explicam o desenho."""
    client = client or bigquery.Client(project=settings.BILLING_PROJECT_ID)
    destino = f"{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.{TABELA}"

    job = client.load_table_from_dataframe(
        df, destino,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    )
    job.result()

    # a documentação vive junto do dado, não só no repositório
    tabela = client.get_table(destino)
    tabela.description = DESCRICAO
    campos = [
        bigquery.SchemaField(
            f.name, f.field_type, mode=f.mode,
            description=DESCRICAO_COLUNAS.get(f.name),
        )
        for f in tabela.schema
    ]
    tabela.schema = campos
    client.update_table(tabela, ["description", "schema"])

    return destino


def ler_gold(client=None) -> pd.DataFrame:
    """
    Lê a base de volta do BigQuery.

    Existe para que a Gold seja consumível e não apenas escrita. O parquet local
    continua sendo a cópia de trabalho da modelagem, por ser mais rápido; esta
    função serve à reprodução em outro ambiente e à conferência do que foi
    publicado.
    """
    client = client or bigquery.Client(project=settings.BILLING_PROJECT_ID)
    origem = f"{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.{TABELA}"
    return client.query(f"SELECT * FROM `{origem}`").to_dataframe()


def main():
    client = bigquery.Client(project=settings.BILLING_PROJECT_ID)

    df = carregar_local()
    print(f"base local: {len(df):,} linhas x {df.shape[1]} colunas")

    destino = publicar(df, client)
    tabela = client.get_table(destino)
    print(f"\npublicado: {destino}")
    print(f"  {tabela.num_rows:,} linhas | {tabela.num_bytes/1e6:.1f} MB")

    print(f"\ndataset {settings.GOLD_DATASET} agora:")
    for t in sorted(client.list_tables(settings.GOLD_DATASET), key=lambda x: x.table_id):
        tb = client.get_table(f"{settings.GOLD_DATASET}.{t.table_id}")
        fase = "Fase 3" if t.table_id == TABELA else "Fase 2"
        print(f"  {t.table_id:24s} {tb.num_rows:>10,} linhas   {fase}")

    relatorio = os.path.join(settings.PATHS["reports"], "gold_fase3.json")
    with open(relatorio, "w", encoding="utf-8") as f:
        json.dump({
            "tabela": destino,
            "linhas": tabela.num_rows,
            "megabytes": round(tabela.num_bytes / 1e6, 1),
            "colunas": [f_.name for f_ in tabela.schema],
            "linhagem": {
                "gold_fase_2": "meta_municipio, de indicador_municipio",
                "microdados": "basedosdados.br_inep_avaliacao_alfabetizacao.alunos",
                "externas": ["br_inep_ideb", "br_ibge_pib", "br_ibge_populacao"],
            },
        }, f, indent=2, ensure_ascii=False)
    print(f"\nrelatório: {relatorio}")


if __name__ == "__main__":
    main()
