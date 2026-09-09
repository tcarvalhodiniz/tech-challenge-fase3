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
TABELA_RISCO = "risco_municipio"

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


DESCRICAO_RISCO = """Escore de risco educacional por município, para priorização de política pública.

Uma linha por município, com a taxa de alfabetização prevista pelo modelo, o perfil
socioeducacional atribuído por agrupamento e a distância até a meta de 2030.

A taxa prevista é a média das probabilidades individuais dos alunos do município. É
nesse nível que o modelo é confiável: no aluno o ROC-AUC é 0,66, mas as predições
agregadas por município correlacionam 0,83 com a taxa real, porque os erros
individuais não são sistemáticos e se cancelam na média.

A coluna amostra_pequena marca municípios com menos de 30 alunos avaliados, cuja
taxa é instável. Não há classificação de trajetória por município: a variação entre
2023 e 2024 tem desvio de 16 pontos contra ruído amostral de 4,6, e dois pontos no
tempo não separam mudança real de sorteio."""

DESCRICAO_COLUNAS_RISCO = {
    "id_municipio": "Código IBGE de 7 dígitos",
    "sigla_uf": "UF do município",
    "regiao": "Região do município",
    "alunos": "Alunos avaliados em 2024 no município",
    "taxa_prevista": "Taxa de alfabetização prevista pelo modelo, em %",
    "taxa_observada": "Taxa de alfabetização observada em 2024, em %",
    "taxa_anterior": "Taxa observada em 2023, em %",
    "ideb": "IDEB dos anos iniciais em 2023",
    "amostra_pequena": "Verdadeiro quando há menos de 30 alunos avaliados",
    "perfil_nome": "Perfil socioeducacional atribuído por agrupamento",
    "meta_2030": "Meta de alfabetização do município para 2030, em %",
    "realizado_2023": "Realizado em 2023, da Gold da Fase 2",
    "realizado_2024": "Realizado em 2024, da Gold da Fase 2",
    "distancia_meta_2030": "Pontos percentuais entre o realizado de 2024 e a meta de 2030",
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


def publicar_risco(client=None) -> str:
    """Publica o escore por município, que é a saída consumível por um gestor."""
    client = client or bigquery.Client(project=settings.BILLING_PROJECT_ID)
    caminho = os.path.join(settings.PATHS["processed"], "risco_municipio.parquet")
    df = pd.read_parquet(caminho)

    descartar = [c for c in ("perfil", "pib_per_capita_log", "populacao_log") if c in df.columns]
    df = df.drop(columns=descartar)
    for c in df.select_dtypes(include=["Float64"]).columns:
        df[c] = df[c].astype("float64")
    for c in df.select_dtypes(include=["Int64"]).columns:
        df[c] = df[c].astype("float64" if df[c].isna().any() else "int64")

    destino = f"{settings.BILLING_PROJECT_ID}.{settings.GOLD_DATASET}.{TABELA_RISCO}"
    client.load_table_from_dataframe(
        df, destino,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    ).result()

    tabela = client.get_table(destino)
    tabela.description = DESCRICAO_RISCO
    tabela.schema = [
        bigquery.SchemaField(f.name, f.field_type, mode=f.mode,
                             description=DESCRICAO_COLUNAS_RISCO.get(f.name))
        for f in tabela.schema
    ]
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

    if os.path.exists(os.path.join(settings.PATHS["processed"], "risco_municipio.parquet")):
        destino_risco = publicar_risco(client)
        tr = client.get_table(destino_risco)
        print(f"publicado: {destino_risco}")
        print(f"  {tr.num_rows:,} linhas | {tr.num_bytes/1e6:.1f} MB")

    print(f"\ndataset {settings.GOLD_DATASET} agora:")
    for t in sorted(client.list_tables(settings.GOLD_DATASET), key=lambda x: x.table_id):
        tb = client.get_table(f"{settings.GOLD_DATASET}.{t.table_id}")
        fase = "Fase 3" if t.table_id in (TABELA, TABELA_RISCO) else "Fase 2"
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
