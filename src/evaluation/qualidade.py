"""
Validação de qualidade da base de modelagem, com quarentena.

Cada regra separa registros aprovados dos reprovados e anexa o motivo, para que a
reprovação seja diagnosticável em vez de apenas contada. O percentual aprovado é
confrontado com o limiar de `config/settings.py`, e ficar abaixo dele interrompe a
execução: publicar um modelo treinado sobre base degradada é pior que não publicar.

Uso:
    python -m src.evaluation.qualidade
"""

import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _RAIZ)

import pandas as pd

from config import settings


class QualidadeInsuficiente(Exception):
    """Levantada quando a base não atinge o percentual mínimo de aprovação."""


def _regras(df: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Condições que reprovam um registro. Cada uma vira um motivo de quarentena.

    As faixas vêm de `settings.LIMITES`; o IDEB varia de 0 a 10 por definição da
    escala do próprio indicador.
    """
    lo_pct, hi_pct = settings.LIMITES["indicador_pct"]

    reprovacoes = {
        "alvo_ausente": df[settings.ALVO].isna(),
        "alvo_fora_do_dominio": ~df[settings.ALVO].isin([0, 1]),
        "municipio_malformado": ~df[settings.COLUNA_GRUPO].astype(str).str.fullmatch(r"\d{7}"),
    }

    for col in ["taxa_municipio_ant", "taxa_uf_ant", "meta_municipio", "aprovacao_municipio"]:
        if col in df.columns:
            v = df[col]
            reprovacoes[f"{col}_fora_da_faixa"] = v.notna() & ((v < lo_pct) | (v > hi_pct))

    if "ideb_municipio" in df.columns:
        v = df["ideb_municipio"]
        reprovacoes["ideb_fora_da_escala"] = v.notna() & ((v < 0) | (v > 10))

    return reprovacoes


def avaliar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Separa aprovados e quarentena, com o motivo de cada reprovação."""
    reprovacoes = _regras(df)

    motivos = pd.Series([[] for _ in range(len(df))], index=df.index)
    for nome, condicao in reprovacoes.items():
        atingidos = condicao.fillna(False)
        motivos[atingidos] = motivos[atingidos].apply(lambda m, n=nome: m + [n])

    reprovado = motivos.apply(len) > 0
    aprovados = df[~reprovado]
    quarentena = df[reprovado].copy()
    quarentena["motivo_quarentena"] = motivos[reprovado].apply("; ".join)

    total = len(df)
    resumo = {
        "total": total,
        "aprovados": int(len(aprovados)),
        "quarentena": int(len(quarentena)),
        "pct_qualidade": round(100 * len(aprovados) / total, 4) if total else 0.0,
        "motivos": {
            nome: int(cond.fillna(False).sum()) for nome, cond in reprovacoes.items()
        },
    }
    return aprovados, quarentena, resumo


def aplicar_gate(resumo: dict) -> None:
    """Interrompe a execução quando a aprovação fica abaixo do limiar."""
    minimo = settings.GATES["pct_qualidade_minimo"]
    if resumo["pct_qualidade"] < minimo:
        reprovando = {k: v for k, v in resumo["motivos"].items() if v > 0}
        raise QualidadeInsuficiente(
            f"qualidade em {resumo['pct_qualidade']:.2f}%, abaixo do mínimo de {minimo}%. "
            f"Motivos: {reprovando}"
        )


def main():
    origem = os.path.join(settings.PATHS["processed"], "base_modelagem.parquet")
    df = pd.read_parquet(origem)

    aprovados, quarentena, resumo = avaliar(df)

    print(f"total ......... {resumo['total']:,}")
    print(f"aprovados ..... {resumo['aprovados']:,}")
    print(f"quarentena .... {resumo['quarentena']:,}")
    print(f"qualidade ..... {resumo['pct_qualidade']:.4f}% "
          f"(mínimo {settings.GATES['pct_qualidade_minimo']}%)")

    reprovando = {k: v for k, v in resumo["motivos"].items() if v > 0}
    if reprovando:
        print("\nmotivos com ocorrência:")
        for nome, n in sorted(reprovando.items(), key=lambda x: -x[1]):
            print(f"  {nome:34s} {n:>8,}")
    else:
        print("\nnenhuma regra foi violada")

    if len(quarentena):
        destino = os.path.join(settings.PATHS["processed"], "quarentena.parquet")
        quarentena.to_parquet(destino, index=False)
        print(f"\nquarentena preservada em {destino}")

    relatorio = os.path.join(settings.PATHS["reports"], "qualidade.json")
    with open(relatorio, "w", encoding="utf-8") as f:
        json.dump(resumo, f, indent=2, ensure_ascii=False)
    print(f"relatório: {relatorio}")

    aplicar_gate(resumo)
    print("\ngate de qualidade aprovado")


if __name__ == "__main__":
    main()
