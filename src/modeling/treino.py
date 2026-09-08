"""
Comparação de modelos, otimização e avaliação final.

A ordem é deliberada: primeiro o baseline da classe majoritária, que define o piso
que qualquer modelo precisa superar para justificar sua existência; depois a
regressão logística, que é interpretável e rápida; e só então o modelo de árvore.

Todos passam pela mesma pipeline e pela mesma validação agrupada por município, o
que torna a comparação honesta.

Uso:
    python -m src.modeling.treino
"""

import json
import os
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RandomizedSearchCV, cross_validate

from config import settings
from src.modeling.pipeline import (
    carregar,
    construir_pipeline,
    separar,
    validador_cruzado,
)

METRICAS = ["roc_auc", "average_precision", "accuracy", "f1"]

CANDIDATOS = {
    "baseline_classe_majoritaria": DummyClassifier(strategy="prior"),
    "regressao_logistica": LogisticRegression(max_iter=500, random_state=settings.SEED),
    "gradient_boosting": HistGradientBoostingClassifier(random_state=settings.SEED),
}

# Espaço de busca do modelo de árvore. Mantido curto de propósito: com 65 colunas e
# 1,5 milhão de linhas, o ganho de uma busca maior não compensa o tempo.
ESPACO = {
    "modelo__max_iter": [100, 200, 300],
    "modelo__learning_rate": [0.05, 0.1, 0.2],
    "modelo__max_depth": [None, 6, 10],
    "modelo__min_samples_leaf": [20, 50, 100],
    "modelo__l2_regularization": [0.0, 1.0],
}


def comparar(X, y, grupos) -> dict:
    """Validação cruzada agrupada para cada candidato."""
    resultados = {}
    for nome, estimador in CANDIDATOS.items():
        inicio = time.time()
        scores = cross_validate(
            construir_pipeline(estimador),
            X, y,
            groups=grupos,
            cv=validador_cruzado(),
            scoring=METRICAS,
            return_train_score=True,
            n_jobs=1,
        )
        resultados[nome] = {
            m: {
                "teste_media": round(float(scores[f"test_{m}"].mean()), 4),
                "teste_desvio": round(float(scores[f"test_{m}"].std()), 4),
                "treino_media": round(float(scores[f"train_{m}"].mean()), 4),
            }
            for m in METRICAS
        }
        resultados[nome]["segundos"] = round(time.time() - inicio, 1)
        print(f"  {nome:30s} ROC-AUC {resultados[nome]['roc_auc']['teste_media']:.4f} "
              f"(±{resultados[nome]['roc_auc']['teste_desvio']:.4f})  "
              f"{resultados[nome]['segundos']}s")
    return resultados


def otimizar(X, y, grupos, n_iter=8):
    """
    Busca aleatória sobre o modelo de árvore, com a mesma validação agrupada.

    Três folds em vez de cinco: a busca multiplica o número de ajustes, e o ganho
    de precisão do quinto fold não paga o tempo nesta etapa.
    """
    busca = RandomizedSearchCV(
        construir_pipeline(CANDIDATOS["gradient_boosting"]),
        param_distributions=ESPACO,
        n_iter=n_iter,
        scoring="roc_auc",
        cv=validador_cruzado(n_splits=3),
        random_state=settings.SEED,
        n_jobs=1,
        refit=True,
    )
    busca.fit(X, y, groups=grupos)
    return busca


def avaliar(pipe, X_treino, y_treino, X_teste, y_teste) -> dict:
    """Métricas no conjunto retido, com o desempenho de treino para comparação."""
    from sklearn.metrics import (
        accuracy_score, average_precision_score, f1_score, roc_auc_score,
    )

    def calcular(X, y):
        prob = pipe.predict_proba(X)[:, 1]
        pred = pipe.predict(X)
        return {
            "roc_auc": round(float(roc_auc_score(y, prob)), 4),
            "average_precision": round(float(average_precision_score(y, prob)), 4),
            "accuracy": round(float(accuracy_score(y, pred)), 4),
            "f1": round(float(f1_score(y, pred)), 4),
        }

    return {"treino": calcular(X_treino, y_treino), "teste": calcular(X_teste, y_teste)}


def teto_alcancavel(y_teste, grupos_teste) -> float:
    """
    Acurácia máxima que informação de município consegue entregar.

    Substitui o modelo pela taxa real do município no próprio ano, que é o
    oráculo removido pela correção de vazamento e indisponível na prática. O que
    ficar acima disso exigiria variáveis de aluno, professor ou família, que a
    base não tem.
    """
    from sklearn.metrics import accuracy_score

    taxa_real = y_teste.groupby(grupos_teste.values).transform("mean")
    return float(accuracy_score(y_teste, (taxa_real >= 0.5).astype(int)))


def verificar_gates(final: dict, y_teste, grupos_teste) -> dict:
    """
    Confronta o resultado com os limiares de `config/settings.py`.

    O gate de acurácia é relativo ao teto medido, não a um valor absoluto: o
    arquivo de configuração registra por que o critério original foi revisado.
    """
    g = settings.GATES
    baseline = float(max(y_teste.mean(), 1 - y_teste.mean()))
    teto = teto_alcancavel(y_teste, grupos_teste)
    gap = final["treino"]["roc_auc"] - final["teste"]["roc_auc"]

    ganho_modelo = final["teste"]["accuracy"] - baseline
    ganho_teto = teto - baseline
    captura = ganho_modelo / ganho_teto if ganho_teto > 0 else 0.0

    checagens = {
        "roc_auc_minimo": {
            "limiar": g["roc_auc_minimo"],
            "obtido": final["teste"]["roc_auc"],
            "passou": final["teste"]["roc_auc"] >= g["roc_auc_minimo"],
        },
        "captura_minima_do_teto": {
            "limiar": g["captura_minima_do_teto"],
            "obtido": round(captura, 4),
            "passou": captura >= g["captura_minima_do_teto"],
        },
        "gap_overfitting_maximo": {
            "limiar": g["gap_overfitting_maximo"],
            "obtido": round(gap, 4),
            "passou": gap <= g["gap_overfitting_maximo"],
        },
    }
    checagens["referencias"] = {
        "acuracia_do_baseline": round(baseline, 4),
        "acuracia_do_teto_oraculo": round(teto, 4),
        "ganho_do_modelo_pp": round(100 * ganho_modelo, 2),
        "ganho_maximo_alcancavel_pp": round(100 * ganho_teto, 2),
    }
    return checagens


def main():
    X, y, grupos = carregar()
    i_treino, i_teste = separar(X, y, grupos)
    X_tr, y_tr, g_tr = X.iloc[i_treino], y.iloc[i_treino], grupos.iloc[i_treino]
    X_te, y_te = X.iloc[i_teste], y.iloc[i_teste]

    print(f"treino {len(X_tr):,} | teste {len(X_te):,}\n")

    print("validação cruzada dos candidatos:")
    comparacao = comparar(X_tr, y_tr, g_tr)

    melhor_nome = max(
        (n for n in comparacao if n != "baseline_classe_majoritaria"),
        key=lambda n: comparacao[n]["roc_auc"]["teste_media"],
    )
    print(f"\nmelhor candidato: {melhor_nome}")

    print("\notimizando hiperparâmetros...")
    busca = otimizar(X_tr, y_tr, g_tr)
    print(f"  ROC-AUC na busca: {busca.best_score_:.4f}")
    for k, v in busca.best_params_.items():
        print(f"  {k.replace('modelo__',''):22s} {v}")

    final = avaliar(busca.best_estimator_, X_tr, y_tr, X_te, y_te)
    print(f"\nconjunto retido:")
    for m in METRICAS:
        print(f"  {m:20s} treino {final['treino'][m]:.4f}   teste {final['teste'][m]:.4f}")

    gates = verificar_gates(final, y_te, grupos.iloc[i_teste])
    ref = gates["referencias"]
    print(f"\nreferências de acurácia:")
    print(f"  baseline (classe majoritária) ... {ref['acuracia_do_baseline']:.4f}")
    print(f"  modelo ......................... {final['teste']['accuracy']:.4f} "
          f"({ref['ganho_do_modelo_pp']:+.2f} pp)")
    print(f"  teto (oráculo do município) .... {ref['acuracia_do_teto_oraculo']:.4f} "
          f"({ref['ganho_maximo_alcancavel_pp']:+.2f} pp)")

    print("\ngates:")
    for nome, c in gates.items():
        if nome == "referencias":
            continue
        print(f"  {nome:26s} limiar {c['limiar']:<7} obtido {c['obtido']:<9} "
              f"{'passou' if c['passou'] else 'FALHOU'}")

    os.makedirs(settings.PATHS["models"], exist_ok=True)
    destino = os.path.join(settings.PATHS["models"], "modelo.joblib")
    joblib.dump(busca.best_estimator_, destino)

    relatorio = {
        "comparacao_validacao_cruzada": comparacao,
        "melhor_candidato": melhor_nome,
        "melhores_hiperparametros": {
            k.replace("modelo__", ""): v for k, v in busca.best_params_.items()
        },
        "roc_auc_na_busca": round(float(busca.best_score_), 4),
        "conjunto_retido": final,
        "gates": gates,
    }
    caminho = os.path.join(settings.PATHS["reports"], "modelagem.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, indent=2, ensure_ascii=False)

    print(f"\nmodelo:    {destino}")
    print(f"relatório: {caminho}")

    reprovados = [n for n, c in gates.items() if n != "referencias" and not c["passou"]]
    if reprovados:
        raise SystemExit(f"gates reprovados: {', '.join(reprovados)}")


if __name__ == "__main__":
    main()
