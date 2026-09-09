"""
Orquestração da pipeline completa.

Um comando executa da extração à publicação. As dependências são declaradas, não
implícitas na ordem em que alguém lembra de rodar os notebooks, e cada etapa
verifica se o que ela precisa existe antes de começar.

Duas etapas carregam gates que interrompem a execução: a validação de qualidade,
quando a aprovação cai abaixo do mínimo, e o treino, quando o modelo não alcança o
desempenho declarado. Falhar é o comportamento correto nesses casos — publicar um
modelo ruim custa mais que não publicar nenhum.

Uso:
    GOOGLE_APPLICATION_CREDENTIALS=chave.json python -m src.pipeline
    python -m src.pipeline --somente-local     # pula o que precisa do BigQuery
    python -m src.pipeline --do-inicio         # refaz etapas já materializadas
"""

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import dataclass, field

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from config import settings

PROCESSED = settings.PATHS["processed"]
MODELS = settings.PATHS["models"]


@dataclass
class Etapa:
    nome: str
    modulo: str
    descricao: str
    produz: list[str] = field(default_factory=list)
    requer: list[str] = field(default_factory=list)
    precisa_bigquery: bool = False
    tem_gate: bool = False


ETAPAS = [
    Etapa(
        "base_analitica", "src.preprocessing.base_analitica",
        "microdados juntados com o contexto municipal da Gold da Fase 2",
        produz=[f"{PROCESSED}/base_analitica.parquet"],
        precisa_bigquery=True,
    ),
    Etapa(
        "enriquecimento", "src.preprocessing.enriquecimento",
        "indicadores socioeconômicos públicos por município",
        produz=[f"{PROCESSED}/externo_municipio.parquet"],
        precisa_bigquery=True,
    ),
    Etapa(
        "features", "src.preprocessing.features",
        "exclusão de vazamento, agregados defasados e base de modelagem",
        requer=[f"{PROCESSED}/base_analitica.parquet"],
        produz=[f"{PROCESSED}/base_modelagem.parquet"],
    ),
    Etapa(
        "qualidade", "src.evaluation.qualidade",
        "validação com quarentena; interrompe abaixo do mínimo de aprovação",
        requer=[f"{PROCESSED}/base_modelagem.parquet"],
        tem_gate=True,
    ),
    Etapa(
        "treino", "src.modeling.treino",
        "comparação, otimização e gates de desempenho",
        requer=[f"{PROCESSED}/base_modelagem.parquet"],
        produz=[f"{MODELS}/modelo.joblib"],
        tem_gate=True,
    ),
    Etapa(
        "avaliacao", "src.evaluation.avaliacao",
        "curvas, calibração, agregação por município e curva de aprendizado",
        requer=[f"{MODELS}/modelo.joblib"],
    ),
    Etapa(
        "interpretabilidade", "src.evaluation.interpretabilidade",
        "importância por permutação e SHAP",
        requer=[f"{MODELS}/modelo.joblib"],
    ),
    Etapa(
        "aplicacao", "src.modeling.aplicacao",
        "escore de risco, perfis de território e ritmo até a meta",
        requer=[f"{MODELS}/modelo.joblib"],
        produz=[f"{PROCESSED}/risco_municipio.parquet"],
        precisa_bigquery=True,
    ),
    Etapa(
        "publicar_gold", "src.export.publicar_gold",
        "publicação das tabelas Gold da fase no BigQuery",
        requer=[f"{PROCESSED}/base_modelagem.parquet"],
        precisa_bigquery=True,
    ),
]


def _faltando(caminhos: list[str]) -> list[str]:
    return [c for c in caminhos if not os.path.exists(c)]


def executar(etapa: Etapa) -> dict:
    """Roda o `main()` do módulo da etapa e devolve o resultado."""
    inicio = time.time()

    ausentes = _faltando(etapa.requer)
    if ausentes:
        return {
            "etapa": etapa.nome, "situacao": "bloqueada",
            "detalhe": f"faltam entradas: {', '.join(os.path.basename(a) for a in ausentes)}",
            "segundos": 0.0,
        }

    modulo = importlib.import_module(etapa.modulo)
    modulo.main()

    return {
        "etapa": etapa.nome, "situacao": "concluida",
        "segundos": round(time.time() - inicio, 1),
    }


def main():
    ap = argparse.ArgumentParser(description="Executa a pipeline completa.")
    ap.add_argument("--somente-local", action="store_true",
                    help="pula as etapas que dependem do BigQuery")
    ap.add_argument("--do-inicio", action="store_true",
                    help="refaz etapas cujos artefatos já existem")
    args = ap.parse_args()

    tem_credencial = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    if not tem_credencial and not args.somente_local:
        print("aviso: GOOGLE_APPLICATION_CREDENTIALS não definida; "
              "as etapas que usam BigQuery serão puladas\n")

    execucao, inicio_total = [], time.time()

    for i, etapa in enumerate(ETAPAS, 1):
        cabecalho = f"[{i}/{len(ETAPAS)}] {etapa.nome}"
        print(f"\n{'=' * 72}\n{cabecalho}  —  {etapa.descricao}\n{'=' * 72}")

        if etapa.precisa_bigquery and (args.somente_local or not tem_credencial):
            print("pulada: depende do BigQuery")
            execucao.append({"etapa": etapa.nome, "situacao": "pulada",
                             "detalhe": "sem credencial ou --somente-local", "segundos": 0.0})
            continue

        if etapa.produz and not args.do_inicio and not _faltando(etapa.produz):
            print("pulada: artefatos já existem (use --do-inicio para refazer)")
            execucao.append({"etapa": etapa.nome, "situacao": "pulada",
                             "detalhe": "artefatos presentes", "segundos": 0.0})
            continue

        try:
            resultado = executar(etapa)
        except Exception as erro:
            # gates interrompem de propósito: a pipeline para e diz por quê
            execucao.append({"etapa": etapa.nome, "situacao": "falhou",
                             "detalhe": f"{type(erro).__name__}: {erro}", "segundos": 0.0})
            _encerrar(execucao, inicio_total)
            print(f"\nPIPELINE INTERROMPIDA em '{etapa.nome}'")
            print(f"  {type(erro).__name__}: {erro}")
            raise SystemExit(1)

        execucao.append(resultado)
        if resultado["situacao"] == "bloqueada":
            print(f"bloqueada: {resultado['detalhe']}")

    _encerrar(execucao, inicio_total)


def _encerrar(execucao: list[dict], inicio: float) -> None:
    """Resumo na tela e registro em arquivo, para comparar execuções."""
    total = round(time.time() - inicio, 1)

    print(f"\n{'=' * 72}\nresumo\n{'=' * 72}")
    for r in execucao:
        marca = {"concluida": "ok", "pulada": "--", "bloqueada": "!!", "falhou": "XX"}[r["situacao"]]
        extra = f"  {r.get('detalhe', '')}" if r.get("detalhe") else ""
        print(f"  {marca}  {r['etapa']:22s} {r['segundos']:>7.1f}s{extra}")
    print(f"\ntempo total: {total}s")

    destino = os.path.join(settings.PATHS["reports"], "execucao_pipeline.json")
    os.makedirs(settings.PATHS["reports"], exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({"segundos_total": total, "etapas": execucao}, f, indent=2, ensure_ascii=False)
    print(f"registro: {destino}")


if __name__ == "__main__":
    main()
