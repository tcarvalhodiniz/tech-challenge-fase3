"""
Pipeline de pré-processamento acoplada ao estimador.

Todas as transformações vivem dentro de um único `Pipeline`. Isso não é
organização: é o que impede vazamento entre treino e teste. Um `StandardScaler`
ajustado fora da pipeline aprenderia a média do conjunto inteiro, teste incluído,
e essa informação entraria no treino pela porta dos fundos. Dentro da pipeline,
o `fit` só vê a partição de treino de cada fold.

A separação é agrupada por município. Alunos do mesmo território compartilham
escola, gestão e contexto socioeconômico; deixá-los dos dois lados faria o modelo
reconhecer o município em vez de generalizar para territórios novos.

Uso:
    python -m src.modeling.pipeline
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config import settings

# `sem_historico_municipio` já é um indicador binário construído no passo anterior
# e entra sem transformação. As demais numéricas passam por imputação e escala.
NUMERICAS = [
    "taxa_municipio_ant",
    "alunos_municipio_ant",
    "taxa_uf_ant",
    "meta_municipio",
]
CATEGORICAS = ["rede", "caderno", "sigla_uf", "regiao"]
BINARIAS = ["sem_historico_municipio"]


def construir_preprocessador() -> ColumnTransformer:
    """
    Imputação e transformação por tipo de variável.

    A mediana é preferida à média por ser robusta a distribuições assimétricas.
    O `add_indicator` preserva o fato de o valor estar ausente: a falta aqui é
    sistemática (município sem histórico, meta inexistente para o par ano-rede) e
    carrega informação que a imputação apagaria.
    """
    numerica = Pipeline([
        ("imputacao", SimpleImputer(strategy="median", add_indicator=True)),
        ("escala", StandardScaler()),
    ])

    categorica = Pipeline([
        ("imputacao", SimpleImputer(strategy="most_frequent")),
        # handle_unknown="ignore": um município de teste pode trazer categoria que
        # não apareceu no treino, e isso não pode quebrar a predição
        ("codificacao", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])

    return ColumnTransformer(
        transformers=[
            ("num", numerica, NUMERICAS),
            ("cat", categorica, CATEGORICAS),
            ("bin", "passthrough", BINARIAS),
        ],
        remainder="drop",
    )


def construir_pipeline(estimador) -> Pipeline:
    """Pré-processamento e estimador em um único objeto, com um único `fit`."""
    return Pipeline([
        ("preproc", construir_preprocessador()),
        ("modelo", estimador),
    ])


def carregar() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Devolve features, alvo e a chave de agrupamento."""
    caminho = os.path.join(settings.PATHS["processed"], "base_modelagem.parquet")
    df = pd.read_parquet(caminho)

    y = df[settings.ALVO].astype(int)
    grupos = df[settings.COLUNA_GRUPO]
    X = df.drop(columns=[settings.ALVO, settings.COLUNA_GRUPO])

    # tipos anuláveis do pandas confundem o scikit-learn
    for c in X.select_dtypes(include=["Float64", "Int64"]).columns:
        X[c] = X[c].astype("float64")

    return X, y, grupos


def separar(X, y, grupos, test_size=None, seed=None):
    """
    Separa treino e teste sem partir municípios entre os dois lados.

    Usa `StratifiedGroupKFold` em vez de `GroupShuffleSplit` porque este último
    não estratifica: como os municípios têm taxas bem diferentes entre si, o
    sorteio puro deslocava a proporção de alfabetizados em mais de dois pontos
    entre treino e teste. Um fold do validador estratificado resolve os dois
    requisitos ao mesmo tempo.

    Retorna os índices posicionais das duas partições.
    """
    test_size = settings.TEST_SIZE if test_size is None else test_size
    seed = settings.SEED if seed is None else seed

    n_splits = max(2, round(1 / test_size))
    divisor = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    return next(divisor.split(X, y, groups=grupos))


def validador_cruzado(n_splits=None, seed=None) -> StratifiedGroupKFold:
    """
    Folds agrupados por município e estratificados pelo alvo.

    O agrupamento evita o vazamento territorial; a estratificação mantém a
    proporção de alfabetizados estável entre as partições.
    """
    n_splits = settings.N_FOLDS if n_splits is None else n_splits
    seed = settings.SEED if seed is None else seed
    return StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)


def verificar_vazamento(X, y, i_treino) -> dict:
    """
    Confirma que o pré-processador aprendeu apenas com o treino.

    A prova é comparar a média que o `StandardScaler` guardou com a média do
    conjunto inteiro. Se fossem iguais, o ajuste teria enxergado o teste.

    A média é preferida à mediana do imputador porque é contínua e sensível a
    qualquer mudança na amostra. A mediana de colunas com poucos valores distintos
    (`taxa_uf_ant` tem 92) coincide entre treino e total sem que isso indique
    vazamento, o que tornaria a leitura ambígua.
    """
    from sklearn.dummy import DummyClassifier

    pipe = construir_pipeline(DummyClassifier(strategy="prior"))
    pipe.fit(X.iloc[i_treino], y.iloc[i_treino])

    escala = pipe.named_steps["preproc"].named_transformers_["num"].named_steps["escala"]
    # o imputador acrescenta os indicadores de ausência ao fim, então as primeiras
    # posições correspondem às colunas numéricas originais
    aprendido = dict(zip(NUMERICAS, escala.mean_))

    return {
        col: {
            "media_aprendida_no_treino": round(float(aprendido[col]), 4),
            "media_do_conjunto_inteiro": round(float(X[col].fillna(X[col].median()).mean()), 4),
            "difere": bool(abs(aprendido[col] - X[col].fillna(X[col].median()).mean()) > 1e-6),
        }
        for col in NUMERICAS
    }


def main():
    from sklearn.dummy import DummyClassifier

    X, y, grupos = carregar()
    print(f"{len(X):,} alunos | {X.shape[1]} features | {grupos.nunique():,} municípios")

    i_treino, i_teste = separar(X, y, grupos)
    m_treino = set(grupos.iloc[i_treino])
    m_teste = set(grupos.iloc[i_teste])

    print("\nseparação agrupada por município:")
    print(f"  treino .................. {len(i_treino):>9,} alunos | {len(m_treino):,} municípios")
    print(f"  teste ................... {len(i_teste):>9,} alunos | {len(m_teste):,} municípios")
    print(f"  municípios em comum ..... {len(m_treino & m_teste)}")
    print(f"  alvo positivo (tr/te) ... {100*y.iloc[i_treino].mean():.2f}% / "
          f"{100*y.iloc[i_teste].mean():.2f}%")

    # o pré-processador só é ajustado no treino
    pipe = construir_pipeline(DummyClassifier(strategy="prior"))
    pipe.fit(X.iloc[i_treino], y.iloc[i_treino])

    nomes = pipe.named_steps["preproc"].get_feature_names_out()
    print(f"\ncolunas após o pré-processamento: {len(nomes)}")
    print(f"  amostra: {', '.join(list(nomes)[:6])} ...")

    transformado = pipe.named_steps["preproc"].transform(X.iloc[i_teste])
    print(f"  teste transformado sem erro: {transformado.shape}")

    print("\nfolds da validação cruzada:")
    for i, (tr, te) in enumerate(validador_cruzado().split(X, y, groups=grupos), 1):
        comuns = set(grupos.iloc[tr]) & set(grupos.iloc[te])
        print(f"  fold {i}: treino {len(tr):>9,} | teste {len(te):>8,} | "
              f"municípios em comum {len(comuns)}")

    print("\no pré-processador aprendeu só com o treino?")
    print(f"  {'coluna':22s} {'média treino':>15s} {'média total':>15s}  difere")
    for col, v in verificar_vazamento(X, y, i_treino).items():
        print(f"  {col:22s} {v['media_aprendida_no_treino']:>15.4f} "
              f"{v['media_do_conjunto_inteiro']:>15.4f}  {'sim' if v['difere'] else 'NÃO'}")


if __name__ == "__main__":
    main()
