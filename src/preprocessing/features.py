"""
Engenharia de atributos e tratamento de vazamento.

O ponto central deste módulo é o que ele *remove*. Além da proficiência, que
define o alvo, saem os agregados calculados no mesmo período (a taxa do município
sai dos próprios alunos que se quer prever) e os identificadores de aluno e escola,
que são reaproveitados entre anos.

No lugar dos agregados do mesmo período entram versões defasadas, calculadas com
os dados do ano anterior. Essas existem no momento da predição e não contêm o
desfecho que se quer prever.

Uso:
    python -m src.preprocessing.features
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import pandas as pd

from config import settings

# O ano modelado precisa de um ano anterior para as features defasadas
ANO_ALVO = 2024
ANO_BASE = 2023

# Amostra mínima para o agregado do município ser considerado confiável
MINIMO_ALUNOS_MUNICIPIO = 10


def populacao_modelavel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Alunos com prova aplicada no ano alvo.

    Quem faltou entra na base oficial como não alfabetizado, mas as colunas que
    sinalizam a ausência são as excluídas por vazamento. Esses registros ficariam
    com as mesmas features dos demais e rótulo sempre zero, o que é ruído.
    """
    tem_prova = df["proficiencia"].notna()
    return df[tem_prova & (df["ano"] == ANO_ALVO)].copy()


def agregados_defasados(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Taxa de alfabetização do ano anterior, por município e por UF.

    Só entram municípios com pelo menos `MINIMO_ALUNOS_MUNICIPIO` alunos avaliados:
    abaixo disso a taxa é instável e vira ruído.
    """
    base = df[(df["ano"] == ANO_BASE) & df["proficiencia"].notna()]

    muni = (
        base.groupby(["id_municipio", "rede"])["alfabetizado"]
        .agg(taxa_municipio_ant="mean", alunos_municipio_ant="size")
        .reset_index()
    )
    muni["taxa_municipio_ant"] *= 100
    muni = muni[muni["alunos_municipio_ant"] >= MINIMO_ALUNOS_MUNICIPIO]

    uf = (
        base.groupby(["sigla_uf", "rede"])["alfabetizado"]
        .agg(taxa_uf_ant="mean")
        .reset_index()
    )
    uf["taxa_uf_ant"] *= 100

    return muni, uf


def carregar_externo() -> pd.DataFrame | None:
    """
    Indicadores socioeconômicos por município, se já tiverem sido materializados.

    Ficam opcionais de propósito: a base de modelagem continua sendo construída
    sem acesso ao BigQuery, e o enriquecimento entra quando disponível.
    """
    caminho = os.path.join(settings.PATHS["processed"], "externo_municipio.parquet")
    return pd.read_parquet(caminho) if os.path.exists(caminho) else None


def construir(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica as exclusões e acopla as features defasadas."""
    alvo = populacao_modelavel(df)
    muni, uf = agregados_defasados(df)

    alvo = alvo.merge(muni, on=["id_municipio", "rede"], how="left")
    alvo = alvo.merge(uf, on=["sigla_uf", "rede"], how="left")

    externo = carregar_externo()
    if externo is not None:
        alvo = alvo.merge(externo, on="id_municipio", how="left")

    # município sem histórico é um caso real de partida a frio, não um defeito:
    # marcar a ausência preserva a informação de que não há histórico
    alvo["sem_historico_municipio"] = alvo["taxa_municipio_ant"].isna().astype(int)

    descartar = (
        settings.COLUNAS_VAZAMENTO
        + settings.COLUNAS_AGREGADO_MESMO_PERIODO
        + settings.COLUNAS_ID_INSTAVEL
        + settings.COLUNAS_SEM_USO
        + ["ano"]  # constante por construção: a população é de um único ano
    )
    return alvo.drop(columns=[c for c in descartar if c in alvo.columns])


def resumo(antes: pd.DataFrame, depois: pd.DataFrame) -> dict:
    """Registra o que entrou, o que saiu e por quê."""
    features = [c for c in depois.columns
                if c not in (settings.ALVO, settings.COLUNA_GRUPO)]
    return {
        "populacao": {
            "linhas_na_base": len(antes),
            "linhas_modelaveis": len(depois),
            "ano_modelado": ANO_ALVO,
            "ano_das_features_defasadas": ANO_BASE,
            "municipios": int(depois[settings.COLUNA_GRUPO].nunique()),
            "alvo_positivo_pct": round(100 * depois[settings.ALVO].mean(), 2),
        },
        "exclusoes": {
            "vazamento_direto": settings.COLUNAS_VAZAMENTO,
            "agregado_do_mesmo_periodo": settings.COLUNAS_AGREGADO_MESMO_PERIODO,
            "identificador_instavel": settings.COLUNAS_ID_INSTAVEL,
            "sem_uso": settings.COLUNAS_SEM_USO,
        },
        "features": sorted(features),
        "cobertura_features": {
            c: round(100 * depois[c].notna().mean(), 2) for c in sorted(features)
        },
    }


def main():
    origem = os.path.join(settings.PATHS["processed"], "base_analitica.parquet")
    df = pd.read_parquet(origem)

    modelo = construir(df)
    info = resumo(df, modelo)

    print(f"base .............. {info['populacao']['linhas_na_base']:,} linhas")
    print(f"modeláveis ........ {info['populacao']['linhas_modelaveis']:,} "
          f"(ano {ANO_ALVO}, com prova aplicada)")
    print(f"municípios ........ {info['populacao']['municipios']:,}")
    print(f"alvo positivo ..... {info['populacao']['alvo_positivo_pct']}%")

    print("\nfeatures e cobertura:")
    for c, cob in info["cobertura_features"].items():
        print(f"  {c:28s} {cob:6.2f}%")

    destino = os.path.join(settings.PATHS["processed"], "base_modelagem.parquet")
    modelo.to_parquet(destino, index=False)
    print(f"\ngravado: {destino} ({os.path.getsize(destino)/1e6:.1f} MB)")

    relatorio = os.path.join(settings.PATHS["reports"], "features.json")
    with open(relatorio, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    print(f"relatório: {relatorio}")


if __name__ == "__main__":
    main()
