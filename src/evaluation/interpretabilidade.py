"""
Interpretabilidade do modelo.

Responde às duas perguntas de negócio sobre influência: quais fatores mais
impactam a alfabetização e quais variáveis pesam mais no modelo. São perguntas
distintas, e a diferença importa. O modelo mede associação dentro do que enxerga,
não causa.

Usa duas técnicas complementares. A importância por permutação embaralha uma
variável por vez e mede quanto o desempenho cai, o que é agnóstico ao algoritmo e
opera sobre as colunas originais. O SHAP decompõe cada predição individual e
mostra também a direção do efeito, não só a magnitude.

Uso:
    python -m src.evaluation.interpretabilidade
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
import shap
from sklearn.inspection import permutation_importance

from config import settings
from src.modeling.pipeline import CATEGORICAS, carregar, separar

PALETA = {"pos": "#4C72B0", "neg": "#C44E52", "ref": "#8C8C8C"}

# Amostras: a permutação reajusta a métrica a cada embaralhamento e o SHAP percorre
# as árvores por linha. Amostrar mantém o custo razoável sem mover os resultados.
N_PERMUTACAO = 120_000
N_SHAP = 40_000


def _salvar(fig, nome):
    caminho = os.path.join(settings.PATHS["images"], nome)
    fig.savefig(caminho, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def importancia_permutacao(pipe, X, y, seed=None) -> pd.DataFrame:
    """
    Quanto o ROC-AUC cai ao embaralhar cada variável.

    Roda sobre as colunas originais, antes do one-hot, então o resultado já vem no
    vocabulário do problema em vez de espalhado por 65 colunas codificadas.
    """
    seed = settings.SEED if seed is None else seed
    resultado = permutation_importance(
        pipe, X, y, scoring="roc_auc", n_repeats=5,
        random_state=seed, n_jobs=1,
    )
    return (
        pd.DataFrame({
            "variavel": X.columns,
            "queda_media": resultado.importances_mean,
            "desvio": resultado.importances_std,
        })
        .sort_values("queda_media", ascending=False)
        .reset_index(drop=True)
    )


def fig_permutacao(imp: pd.DataFrame):
    """Ordena as variáveis pela perda de desempenho que sua ausência causa."""
    d = imp[imp["queda_media"] > 0].head(12).iloc[::-1]

    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.42 * len(d))))
    ax.barh(d["variavel"], d["queda_media"], xerr=d["desvio"],
            color=PALETA["pos"], error_kw={"ecolor": PALETA["ref"], "lw": 1})
    ax.set_xlabel("Queda no ROC-AUC ao embaralhar a variável")
    ax.set_title("Importância por permutação", fontsize=12, pad=10)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "12_importancia_permutacao.png")


def shap_agregado(pipe, X, n=N_SHAP, seed=None):
    """
    Valores SHAP somados de volta às variáveis originais.

    O pré-processamento espalha cada categórica em várias colunas. Somar as
    contribuições de todas as colunas de uma mesma variável devolve o efeito no
    nível em que a pergunta foi feita.
    """
    seed = settings.SEED if seed is None else seed
    amostra = X.sample(n=min(n, len(X)), random_state=seed)

    preproc = pipe.named_steps["preproc"]
    transformado = preproc.transform(amostra)
    nomes = list(preproc.get_feature_names_out())

    explicador = shap.TreeExplainer(pipe.named_steps["modelo"])
    valores = explicador.shap_values(transformado)

    # cada coluna codificada volta para a variável que a originou
    def origem(nome):
        limpo = nome.split("__", 1)[-1]
        for c in CATEGORICAS:
            if limpo.startswith(c + "_"):
                return c
        return limpo.replace("missingindicator_", "")

    grupos = pd.Series([origem(n_) for n_ in nomes])
    df_shap = pd.DataFrame(valores, columns=nomes)
    agregado = df_shap.T.groupby(grupos.values).sum().T

    return agregado, amostra


def direcao_do_efeito(agregado: pd.DataFrame, amostra: pd.DataFrame) -> pd.Series:
    """
    Sinal do efeito: valores altos da variável empurram para qual lado?

    Medido pela correlação entre o valor da variável e sua contribuição SHAP. A
    média das contribuições não serve: ela é negativa sempre que a maioria dos
    alunos está abaixo do ponto em que o efeito troca de sinal, o que reflete a
    distribuição da amostra e não o comportamento da variável.

    Só se aplica às numéricas. Uma categórica com vários níveis não tem direção
    única, já que cada nível empurra para um lado.
    """
    direcoes = {}
    for v in agregado.columns:
        if v in CATEGORICAS or not pd.api.types.is_numeric_dtype(amostra.get(v, pd.Series(dtype=object))):
            direcoes[v] = np.nan
            continue
        valores = amostra[v]
        validos = valores.notna().values
        direcoes[v] = (float(np.corrcoef(valores[validos], agregado[v].values[validos])[0, 1])
                       if validos.sum() > 100 else np.nan)
    return pd.Series(direcoes)


def fig_shap(agregado: pd.DataFrame, direcao: pd.Series):
    """Magnitude média de cada variável, colorida pela direção do efeito."""
    media = agregado.abs().mean().sort_values(ascending=False).head(12)

    d = pd.DataFrame({"magnitude": media, "direcao": direcao.reindex(media.index)}).iloc[::-1]
    cores = [PALETA["ref"] if pd.isna(v) else (PALETA["pos"] if v >= 0 else PALETA["neg"])
             for v in d["direcao"]]

    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.42 * len(d))))
    ax.barh(d.index, d["magnitude"], color=cores)
    ax.set_xlabel("Contribuição média absoluta para a predição (SHAP)")
    ax.set_title("Influência das variáveis, por magnitude e direção", fontsize=12, pad=10)
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(color=PALETA["pos"], label="valores altos empurram para alfabetizado"),
        Patch(color=PALETA["neg"], label="valores altos empurram para não alfabetizado"),
        Patch(color=PALETA["ref"], label="categórica, sem direção única"),
    ], frameon=False, loc="lower right", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "13_shap_variaveis.png")


def efeito_do_porte(X: pd.DataFrame, y: pd.Series) -> dict:
    """
    O porte do município importa por si, ou só por vir junto do histórico?

    O SHAP indica que população alta empurra a predição para baixo, mas a
    correlação bruta com o alvo é quase nula. A diferença é entre efeito marginal
    e condicional, e vale separar antes de afirmar que cidade grande alfabetiza
    menos.
    """
    d = X.copy()
    d["alvo"] = y.values
    d["porte"] = pd.qcut(np.expm1(d["log_populacao_municipio"]), 5,
                         labels=["muito pequeno", "pequeno", "médio", "grande", "muito grande"])

    marginal = d.groupby("porte", observed=True)["alvo"].mean().mul(100).round(1)

    com_hist = d[d["taxa_municipio_ant"].notna()].copy()
    com_hist["faixa"] = pd.qcut(com_hist["taxa_municipio_ant"], 4,
                                labels=["baixa", "média-baixa", "média-alta", "alta"])
    condicional = (com_hist.pivot_table(index="faixa", columns="porte", values="alvo",
                                        aggfunc="mean", observed=True).mul(100).round(1))

    return {
        "taxa_por_porte": marginal.to_dict(),
        "amplitude_marginal_pp": round(float(marginal.max() - marginal.min()), 1),
        "taxa_por_porte_e_historico": {
            str(i): {str(c): (None if pd.isna(v) else float(v)) for c, v in linha.items()}
            for i, linha in condicional.iterrows()
        },
    }


def fig_dependencia(agregado: pd.DataFrame, amostra: pd.DataFrame, variavel: str):
    """Como a contribuição da variável mais influente varia com o seu valor."""
    valores = amostra[variavel].values
    contrib = agregado[variavel].values
    validos = ~pd.isna(valores)

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.scatter(valores[validos], contrib[validos], s=6, alpha=0.2,
               color=PALETA["pos"], edgecolors="none")
    ax.axhline(0, color=PALETA["ref"], lw=1, ls="--")
    ax.set_xlabel(variavel)
    ax.set_ylabel("Contribuição para a predição (SHAP)")
    ax.set_title(f"Efeito de {variavel} sobre a predição", fontsize=12, pad=10)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "14_dependencia_shap.png")


def main():
    X, y, grupos = carregar()
    _, i_teste = separar(X, y, grupos)
    X_te, y_te = X.iloc[i_teste], y.iloc[i_teste]

    pipe = joblib.load(os.path.join(settings.PATHS["models"], "modelo.joblib"))

    print(f"importância por permutação em {N_PERMUTACAO:,} alunos...")
    amostra = X_te.sample(n=min(N_PERMUTACAO, len(X_te)), random_state=settings.SEED)
    imp = importancia_permutacao(pipe, amostra, y_te.loc[amostra.index])

    print(f"\n{'variável':30s} {'queda no AUC':>14s}")
    for _, r in imp.head(10).iterrows():
        print(f"  {r['variavel']:28s} {r['queda_media']:>10.4f} ±{r['desvio']:.4f}")

    print(f"\nvalores SHAP em {N_SHAP:,} alunos...")
    agregado, amostra_shap = shap_agregado(pipe, X_te)
    media = agregado.abs().mean().sort_values(ascending=False)
    direcao = direcao_do_efeito(agregado, amostra_shap)

    print(f"\n{'variável':30s} {'magnitude':>10s} {'direção do efeito':>20s}")
    for v in media.head(10).index:
        d_ = direcao[v]
        rotulo = "categórica" if pd.isna(d_) else (f"+{d_:.2f} alfabetiza" if d_ >= 0
                                                  else f"{d_:.2f} não alfab.")
        print(f"  {v:28s} {media[v]:>10.4f} {rotulo:>20s}")

    porte = efeito_do_porte(X_te, y_te)
    print(f"\nefeito do porte do município (amplitude {porte['amplitude_marginal_pp']} p.p.):")
    for k, v in porte["taxa_por_porte"].items():
        print(f"  {str(k):16s} {v:>5.1f}%")

    figuras = [
        fig_permutacao(imp),
        fig_shap(agregado, direcao),
        fig_dependencia(agregado, amostra_shap, media.index[0]),
    ]
    print("\nfiguras:")
    for f in figuras:
        print("  ", os.path.basename(f))

    destino = os.path.join(settings.PATHS["reports"], "interpretabilidade.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({
            "importancia_permutacao": [
                {"variavel": r["variavel"],
                 "queda_roc_auc": round(float(r["queda_media"]), 5),
                 "desvio": round(float(r["desvio"]), 5)}
                for _, r in imp.iterrows()
            ],
            "shap": [
                {"variavel": v,
                 "magnitude_media": round(float(media[v]), 5),
                 "direcao_efeito": (None if pd.isna(direcao[v]) else round(float(direcao[v]), 4))}
                for v in media.index
            ],
            "efeito_do_porte": porte,
            "amostras": {"permutacao": len(amostra), "shap": len(amostra_shap)},
        }, f, indent=2, ensure_ascii=False)
    print(f"\nrelatório: {destino}")


if __name__ == "__main__":
    main()
