"""
Análise exploratória da base analítica.

Gera as figuras de `images/` e o resumo estatístico de `reports/`. Cada função
responde a uma pergunta específica; nenhuma imprime conclusão — a leitura fica
no relatório, que é escrito a partir destes números.

Uso:
    python -m src.visualization.eda
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import settings

PALETA = {"nao": "#C44E52", "sim": "#4C72B0", "neutro": "#8C8C8C", "destaque": "#DD8452"}
ORDEM_REGIAO = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]


def _salvar(fig, nome):
    os.makedirs(settings.PATHS["images"], exist_ok=True)
    caminho = os.path.join(settings.PATHS["images"], nome)
    fig.savefig(caminho, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def fig_vazamento(df):
    """A prova visual de que `proficiencia` define o alvo."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    fez = df[df["proficiencia"].notna()]
    for valor, cor, rotulo in [
        (0, PALETA["nao"], "Não alfabetizado"),
        (1, PALETA["sim"], "Alfabetizado"),
    ]:
        ax.hist(fez.loc[fez[settings.ALVO] == valor, "proficiencia"],
                bins=120, alpha=0.75, color=cor, label=rotulo)
    ax.axvline(settings.PONTO_CORTE_SAEB, color="black", ls="--", lw=1.8)
    ax.annotate(f"corte Saeb = {settings.PONTO_CORTE_SAEB}",
                xy=(settings.PONTO_CORTE_SAEB, ax.get_ylim()[1] * 0.92),
                xytext=(12, 0), textcoords="offset points", fontsize=10)
    ax.set_title("Distribuição da proficiência por classe do alvo", fontsize=13, pad=12)
    ax.set_xlabel("Proficiência (escala Saeb)")
    ax.set_ylabel("Alunos")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "01_vazamento_proficiencia.png")


def fig_alvo_por_regiao(df):
    """Indicador oficial (ausente conta como não alfabetizado) x só quem fez a prova."""
    oficial = df.groupby("regiao")[settings.ALVO].mean().mul(100)
    fez = df[df["proficiencia"].notna()]
    testado = fez.groupby("regiao")[settings.ALVO].mean().mul(100)
    comp = pd.DataFrame({"oficial": oficial, "testado": testado}).reindex(ORDEM_REGIAO)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(comp))
    ax.bar(x - 0.2, comp["oficial"], 0.4, label="Indicador oficial", color=PALETA["neutro"])
    ax.bar(x + 0.2, comp["testado"], 0.4, label="Somente quem fez a prova", color=PALETA["sim"])
    for i, (o, t) in enumerate(zip(comp["oficial"], comp["testado"])):
        ax.text(i - 0.2, o + 0.8, f"{o:.1f}", ha="center", fontsize=9)
        ax.text(i + 0.2, t + 0.8, f"{t:.1f}", ha="center", fontsize=9)
    ax.set_xticks(x, comp.index)
    ax.set_ylabel("% de alunos alfabetizados")
    ax.set_title("Taxa de alfabetização por região: indicador oficial e somente testados",
                 fontsize=12, pad=12)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "02_alvo_por_regiao.png")


def fig_ausencia(df):
    """Quem não fez a prova, por região — entra no indicador como não alfabetizado."""
    aus = df.groupby("regiao")["proficiencia"].apply(lambda s: 100 * s.isna().mean())
    aus = aus.reindex(ORDEM_REGIAO).sort_values()

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(aus.index, aus.values, color=PALETA["destaque"])
    for i, v in enumerate(aus.values):
        ax.text(v + 0.25, i, f"{v:.1f}%", va="center", fontsize=10)
    ax.set_xlabel("% de alunos sem prova aplicada")
    ax.set_title("Alunos sem prova aplicada, por região", fontsize=13, pad=12)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "03_ausencia_por_regiao.png")


def fig_contexto(df):
    """Correlação das variáveis de contexto com o alvo, entre quem fez a prova."""
    fez = df[df["proficiencia"].notna()]
    cols = ["taxa_municipio", "meta_municipio", "gap_municipio", "taxa_uf"]
    corr = fez[cols + [settings.ALVO]].corr()[settings.ALVO].drop(settings.ALVO).sort_values()

    fig, ax = plt.subplots(figsize=(8, 3.6))
    cores = [PALETA["nao"] if v < 0 else PALETA["sim"] for v in corr.values]
    ax.barh(corr.index, corr.values, color=cores)
    for i, v in enumerate(corr.values):
        deslocamento = 0.012 if v >= 0 else -0.012
        ax.text(v + deslocamento, i, f"{v:+.3f}", va="center",
                ha="left" if v >= 0 else "right", fontsize=10)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlim(-0.35, 0.45)
    ax.set_xlabel("Correlação com o alvo")
    ax.set_title("Correlação das variáveis de contexto com o alvo", fontsize=13, pad=12)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "04_correlacao_contexto.png")


def fig_taxa_municipio(df):
    """Distribuição da taxa do município, separada pelo desfecho do aluno."""
    fez = df[df["proficiencia"].notna()]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for valor, cor, rotulo in [
        (0, PALETA["nao"], "Não alfabetizado"),
        (1, PALETA["sim"], "Alfabetizado"),
    ]:
        ax.hist(fez.loc[fez[settings.ALVO] == valor, "taxa_municipio"].dropna(),
                bins=60, alpha=0.65, color=cor, label=rotulo, density=True)
    ax.set_xlabel("Taxa de alfabetização do município (%)")
    ax.set_ylabel("Densidade")
    ax.set_title("Taxa de alfabetização do município, por desfecho do aluno",
                 fontsize=13, pad=12)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return _salvar(fig, "05_taxa_municipio_por_alvo.png")


def fig_ausentes(df):
    """Quanto da classe negativa é ausência e não reprovação na prova."""
    zeros = df[df[settings.ALVO] == 0]
    ausentes = int(zeros["proficiencia"].isna().sum())
    testados = len(zeros) - ausentes

    fig, ax = plt.subplots(figsize=(8, 2.6))
    ax.barh([""], [testados], color=PALETA["nao"], label=f"Fez a prova e não atingiu ({testados:,})")
    ax.barh([""], [ausentes], left=[testados], color=PALETA["neutro"],
            label=f"Ausente, sem prova ({ausentes:,})")
    ax.set_xlabel("Alunos classificados como não alfabetizados")
    ax.set_title("Composição da classe \"não alfabetizado\"", fontsize=13, pad=12)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.55), ncol=2)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.set_yticks([])
    return _salvar(fig, "06_composicao_classe_negativa.png")


def estatisticas(df):
    """Números que sustentam o relatório — gravados, não só exibidos."""
    fez = df[df["proficiencia"].notna()]
    zeros = df[df[settings.ALVO] == 0]
    concordancia = float(
        ((fez["proficiencia"] >= settings.PONTO_CORTE_SAEB).astype(int) == fez[settings.ALVO]).mean()
    )

    return {
        "volume": {
            "linhas": len(df),
            "municipios": int(df["id_municipio"].nunique()),
            "escolas": int(df["id_escola"].nunique()),
            "anos": sorted(df["ano"].unique().tolist()),
        },
        "vazamento": {
            "concordancia_corte_vs_alvo": round(100 * concordancia, 4),
            "prof_max_classe_0": float(fez.loc[fez[settings.ALVO] == 0, "proficiencia"].max()),
            "prof_min_classe_1": float(fez.loc[fez[settings.ALVO] == 1, "proficiencia"].min()),
        },
        "ausencia": {
            "alunos_sem_prova": int(df["proficiencia"].isna().sum()),
            "pct_da_base": round(100 * df["proficiencia"].isna().mean(), 2),
            "pct_da_classe_negativa": round(100 * zeros["proficiencia"].isna().mean(), 2),
            "por_regiao": df.groupby("regiao")["proficiencia"]
                            .apply(lambda s: round(100 * s.isna().mean(), 2)).to_dict(),
        },
        "alvo": {
            "taxa_oficial_pct": round(100 * df[settings.ALVO].mean(), 2),
            "taxa_entre_testados_pct": round(100 * fez[settings.ALVO].mean(), 2),
            "por_regiao_testados": fez.groupby("regiao")[settings.ALVO]
                                     .apply(lambda s: round(100 * s.mean(), 2)).to_dict(),
        },
        "correlacoes_contexto": fez[["taxa_municipio", "meta_municipio", "gap_municipio",
                                     "taxa_uf", settings.ALVO]]
                                  .corr()[settings.ALVO].drop(settings.ALVO).round(3).to_dict(),
        "cobertura": {
            c: round(100 * df[c].notna().mean(), 2)
            for c in ["taxa_municipio", "meta_municipio", "gap_municipio", "taxa_uf",
                      "meta_uf", "gap_uf", "sigla_uf"]
        },
    }


def main():
    origem = os.path.join(settings.PATHS["processed"], "base_analitica.parquet")
    df = pd.read_parquet(origem)
    print(f"Base: {len(df):,} linhas")

    figuras = [
        fig_vazamento(df),
        fig_ausentes(df),
        fig_alvo_por_regiao(df),
        fig_ausencia(df),
        fig_contexto(df),
        fig_taxa_municipio(df),
    ]
    print("\nFiguras geradas:")
    for f in figuras:
        print("  ", os.path.basename(f))

    stats = estatisticas(df)
    os.makedirs(settings.PATHS["reports"], exist_ok=True)
    destino = os.path.join(settings.PATHS["reports"], "analise_exploratoria.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\nEstatísticas: {destino}")

    print("\nDestaques:")
    print(f"  concordância corte x alvo ....... {stats['vazamento']['concordancia_corte_vs_alvo']}%")
    print(f"  ausentes na base ................ {stats['ausencia']['pct_da_base']}%")
    print(f"  ausentes dentro da classe 0 ..... {stats['ausencia']['pct_da_classe_negativa']}%")
    print(f"  alvo oficial x entre testados ... {stats['alvo']['taxa_oficial_pct']}% / "
          f"{stats['alvo']['taxa_entre_testados_pct']}%")


if __name__ == "__main__":
    main()
