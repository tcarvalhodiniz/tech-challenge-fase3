"""
Avaliação detalhada do modelo treinado.

Vai além das métricas agregadas do passo anterior: examina como o erro se
distribui, se as probabilidades são confiáveis e se mais dados ajudariam.

Inclui uma verificação que o desempenho por aluno não responde: o quanto o modelo
acerta quando as predições são agregadas por município. Se a ordenação de
territórios for boa mesmo com acerto individual modesto, a aplicação prática do
modelo é essa, e não a decisão sobre uma criança.

Uso:
    python -m src.evaluation.avaliacao
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
from scipy.stats import pearsonr, spearmanr
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    average_precision_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import learning_curve

from config import settings
from src.modeling.pipeline import carregar, construir_pipeline, separar, validador_cruzado

PALETA = {"linha": "#4C72B0", "ref": "#8C8C8C", "destaque": "#C44E52"}


def _salvar(fig, nome):
    os.makedirs(settings.PATHS["images"], exist_ok=True)
    caminho = os.path.join(settings.PATHS["images"], nome)
    fig.savefig(caminho, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def fig_curvas(y, prob):
    """ROC e precisão-revocação lado a lado."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3))

    fpr, tpr, _ = roc_curve(y, prob)
    ax1.plot(fpr, tpr, color=PALETA["linha"], lw=2,
             label=f"modelo (AUC {roc_auc_score(y, prob):.3f})")
    ax1.plot([0, 1], [0, 1], ls="--", color=PALETA["ref"], lw=1, label="aleatório")
    ax1.set_xlabel("Falsos positivos")
    ax1.set_ylabel("Verdadeiros positivos")
    ax1.set_title("Curva ROC", fontsize=12)
    ax1.legend(frameon=False, loc="lower right")

    prec, rec, _ = precision_recall_curve(y, prob)
    ax2.plot(rec, prec, color=PALETA["linha"], lw=2,
             label=f"modelo (AP {average_precision_score(y, prob):.3f})")
    ax2.axhline(y.mean(), ls="--", color=PALETA["ref"], lw=1,
                label=f"taxa base ({y.mean():.3f})")
    ax2.set_xlabel("Revocação")
    ax2.set_ylabel("Precisão")
    ax2.set_title("Curva precisão-revocação", fontsize=12)
    ax2.legend(frameon=False, loc="lower left")

    for ax in (ax1, ax2):
        ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "07_curvas_roc_pr.png")


def fig_matriz(y, pred):
    """Matriz de confusão em proporção da classe verdadeira."""
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    ConfusionMatrixDisplay(
        confusion_matrix(y, pred, normalize="true"),
        display_labels=["Não alfabetizado", "Alfabetizado"],
    ).plot(ax=ax, cmap="Blues", values_format=".3f", colorbar=False)
    ax.set_title("Matriz de confusão (proporção por classe real)", fontsize=11)
    ax.set_xlabel("Predito")
    ax.set_ylabel("Real")
    return _salvar(fig, "08_matriz_confusao.png")


def fig_calibracao(y, prob):
    """
    As probabilidades correspondem à frequência observada?

    Importa mais que a acurácia para o uso pretendido: ordenar territórios por
    risco exige que uma probabilidade de 0,3 signifique de fato 30%.
    """
    fracao, media = calibration_curve(y, prob, n_bins=20, strategy="quantile")

    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    ax.plot([0, 1], [0, 1], ls="--", color=PALETA["ref"], lw=1, label="calibração perfeita")
    ax.plot(media, fracao, "o-", color=PALETA["linha"], lw=1.8, ms=5,
            label=f"modelo (Brier {brier_score_loss(y, prob):.4f})")
    ax.set_xlabel("Probabilidade prevista")
    ax.set_ylabel("Frequência observada")
    ax.set_title("Curva de calibração", fontsize=12)
    ax.legend(frameon=False, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "09_calibracao.png")


def fig_agregacao_municipio(df_mun):
    """Taxa real do município contra a média das probabilidades previstas."""
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(df_mun["prob_media"], df_mun["taxa_real"], s=10, alpha=0.25,
               color=PALETA["linha"], edgecolors="none")
    lims = [0, 1]
    ax.plot(lims, lims, ls="--", color=PALETA["ref"], lw=1)
    r = pearsonr(df_mun["prob_media"], df_mun["taxa_real"])[0]
    ax.set_xlim(0.2, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel("Probabilidade média prevista no município")
    ax.set_ylabel("Taxa real de alfabetização do município")
    ax.set_title(f"Predição agregada por município (r = {r:.3f})", fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "10_agregacao_municipio.png")


def fig_curva_aprendizado(X, y, grupos, pipe):
    """Mais dados melhorariam o modelo, ou o limite é a informação disponível?"""
    tamanhos, treino, validacao = learning_curve(
        pipe, X, y, groups=grupos,
        cv=validador_cruzado(n_splits=3),
        train_sizes=np.linspace(0.15, 1.0, 5),
        scoring="roc_auc", n_jobs=1, shuffle=False,
    )

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot(tamanhos, treino.mean(axis=1), "o-", color=PALETA["destaque"],
            lw=1.8, ms=5, label="treino")
    ax.plot(tamanhos, validacao.mean(axis=1), "o-", color=PALETA["linha"],
            lw=1.8, ms=5, label="validação")
    ax.fill_between(tamanhos, validacao.mean(axis=1) - validacao.std(axis=1),
                    validacao.mean(axis=1) + validacao.std(axis=1),
                    alpha=0.15, color=PALETA["linha"])
    ax.set_xlabel("Alunos no treino")
    ax.set_ylabel("ROC-AUC")
    ax.set_title("Curva de aprendizado", fontsize=12)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    caminho = _salvar(fig, "11_curva_aprendizado.png")

    return caminho, {
        "tamanhos": [int(t) for t in tamanhos],
        "roc_auc_treino": [round(float(v), 4) for v in treino.mean(axis=1)],
        "roc_auc_validacao": [round(float(v), 4) for v in validacao.mean(axis=1)],
    }


def analisar_limiar(y, prob, limiares=(0.50, 0.55, 0.60, 0.65, 0.70, 0.75)) -> list[dict]:
    """
    Troca entre encontrar crianças em risco e sinalizar quem ficaria bem.

    O limiar padrão de 0,5 maximiza acurácia, o que trata falso positivo e falso
    negativo como equivalentes. Aqui não são: sinalizar quem ficaria bem custa uma
    avaliação pedagógica extra, e deixar de sinalizar quem está em risco custa uma
    criança não alfabetizada. A classe 0 é a de interesse.
    """
    from sklearn.metrics import accuracy_score, precision_score, recall_score

    linhas = []
    for t in limiares:
        pred = (prob >= t).astype(int)
        linhas.append({
            "limiar": t,
            "revocacao_em_risco": round(float(recall_score(y, pred, pos_label=0)), 4),
            "precisao_em_risco": round(float(precision_score(y, pred, pos_label=0)), 4),
            "acuracia": round(float(accuracy_score(y, pred)), 4),
        })
    return linhas


def avaliar_por_municipio(y, prob, grupos) -> tuple[pd.DataFrame, dict]:
    """
    Agrega as predições por território e compara com a taxa real.

    O modelo pode errar bastante em cada aluno e ainda assim ordenar municípios
    corretamente, porque os erros individuais se cancelam na média.
    """
    d = pd.DataFrame({"municipio": grupos.values, "real": y.values, "prob": prob})
    mun = d.groupby("municipio").agg(
        taxa_real=("real", "mean"),
        prob_media=("prob", "mean"),
        alunos=("real", "size"),
    ).reset_index()

    # municípios minúsculos tornam a taxa real instável e poluem a comparação
    mun = mun[mun["alunos"] >= 30]

    return mun, {
        "municipios_avaliados": len(mun),
        "correlacao_pearson": round(float(pearsonr(mun["prob_media"], mun["taxa_real"])[0]), 4),
        "correlacao_spearman": round(float(spearmanr(mun["prob_media"], mun["taxa_real"])[0]), 4),
        "erro_medio_absoluto_pp": round(float(100 * (mun["prob_media"] - mun["taxa_real"]).abs().mean()), 2),
    }


def main():
    X, y, grupos = carregar()
    i_treino, i_teste = separar(X, y, grupos)
    X_te, y_te, g_te = X.iloc[i_teste], y.iloc[i_teste], grupos.iloc[i_teste]

    pipe = joblib.load(os.path.join(settings.PATHS["models"], "modelo.joblib"))
    prob = pipe.predict_proba(X_te)[:, 1]
    pred = pipe.predict(X_te)

    print(f"conjunto retido: {len(y_te):,} alunos, {g_te.nunique():,} municípios\n")

    relatorio = classification_report(y_te, pred, output_dict=True,
                                      target_names=["nao_alfabetizado", "alfabetizado"])
    print("por classe:")
    for classe in ["nao_alfabetizado", "alfabetizado"]:
        m = relatorio[classe]
        print(f"  {classe:20s} precisão {m['precision']:.3f}  revocação {m['recall']:.3f}  "
              f"f1 {m['f1-score']:.3f}  n={int(m['support']):,}")

    brier = brier_score_loss(y_te, prob)
    print(f"\nBrier score: {brier:.4f}  (menor é melhor; 0,25 seria chute constante)")

    limiares = analisar_limiar(y_te, prob)
    print("\ntroca no limiar (classe de interesse = em risco):")
    print(f"  {'limiar':>7s} {'encontra':>9s} {'precisão':>9s} {'acurácia':>9s}")
    for l in limiares:
        print(f"  {l['limiar']:>7.2f} {l['revocacao_em_risco']:>9.3f} "
              f"{l['precisao_em_risco']:>9.3f} {l['acuracia']:>9.3f}")

    mun, agregado = avaliar_por_municipio(y_te, prob, g_te)
    print(f"\nagregado por município ({agregado['municipios_avaliados']:,} com 30+ alunos):")
    print(f"  correlação de Pearson ....... {agregado['correlacao_pearson']:.4f}")
    print(f"  correlação de Spearman ...... {agregado['correlacao_spearman']:.4f}")
    print(f"  erro médio absoluto ......... {agregado['erro_medio_absoluto_pp']:.2f} p.p.")

    figuras = [
        fig_curvas(y_te, prob),
        fig_matriz(y_te, pred),
        fig_calibracao(y_te, prob),
        fig_agregacao_municipio(mun),
    ]

    print("\ncalculando a curva de aprendizado...")
    caminho, aprendizado = fig_curva_aprendizado(
        X.iloc[i_treino], y.iloc[i_treino], grupos.iloc[i_treino],
        construir_pipeline(pipe.named_steps["modelo"]),
    )
    figuras.append(caminho)
    print(f"  ROC-AUC de validação por tamanho: "
          f"{' -> '.join(str(v) for v in aprendizado['roc_auc_validacao'])}")

    print("\nfiguras:")
    for f in figuras:
        print("  ", os.path.basename(f))

    destino = os.path.join(settings.PATHS["reports"], "avaliacao.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({
            "por_classe": {k: v for k, v in relatorio.items()
                           if k in ("nao_alfabetizado", "alfabetizado")},
            "acuracia": round(float(relatorio["accuracy"]), 4),
            "brier_score": round(float(brier), 4),
            "analise_limiar": limiares,
            "agregado_por_municipio": agregado,
            "curva_aprendizado": aprendizado,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nrelatório: {destino}")


if __name__ == "__main__":
    main()
