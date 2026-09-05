"""
Configuração central do projeto de predição de alfabetização.

Um único lugar para fontes, semântica de negócio, regras anti-vazamento e os
limiares que interrompem a execução. Trocar AMBIENTE muda de onde os dados vêm
sem alterar a lógica da pipeline.
"""

import os

# "bigquery" (lê da Gold da Fase 2) | "local" (parquet já materializado)
AMBIENTE = os.getenv("AMBIENTE", "bigquery")

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATHS = {
    "raw": os.path.join(RAIZ, "data", "raw"),
    "processed": os.path.join(RAIZ, "data", "processed"),
    "reports": os.path.join(RAIZ, "reports"),
    "images": os.path.join(RAIZ, "images"),
    "models": os.path.join(RAIZ, "models"),
}

# ---------------------------------------------------------------------------
# Fontes
#   Gold: construída no Tech Challenge da Fase 2 (mesmo projeto GCP)
#   Microdados: Base dos Dados (BigQuery público) — grão de aluno
# ---------------------------------------------------------------------------
BILLING_PROJECT_ID = os.getenv("GCP_PROJECT", "tech-challenge-fiap-501217")

GOLD_DATASET = "alfabetizacao_gold"
TABELAS_GOLD = {
    "indicador_municipio": "meta x realizado por municipio, com gap",
    "evolucao_municipio": "trajetoria do indicador rumo a 2030",
    "indicador_uf": "meta x realizado por UF",
}

BD_PROJECT = "basedosdados"
BD_DATASET = "br_inep_avaliacao_alfabetizacao"
TABELA_MICRODADOS = "alunos"  # ~3,87 milhoes de alunos (2023-2024)

# ---------------------------------------------------------------------------
# Semântica de negócio
# ---------------------------------------------------------------------------
# Ponto de corte de proficiência do Saeb (Alfabetiza Brasil 2023)
PONTO_CORTE_SAEB = 743
ALVO = "alfabetizado"  # 0 = nao alfabetizado, 1 = alfabetizado

# ---------------------------------------------------------------------------
# Anti-vazamento (data leakage)
#   `proficiencia` DEFINE o alvo (alfabetizado = proficiencia >= 743).
#   Mantê-la como feature daria acerto perfeito e modelo inútil. As demais só
#   existem depois da prova aplicada — informação indisponível no momento da
#   predição. Todas ficam fora do conjunto de treino.
# ---------------------------------------------------------------------------
COLUNAS_VAZAMENTO = [
    "proficiencia",            # define o alvo diretamente
    "peso_aluno",              # peso amostral pos-prova
    "preenchimento_caderno",   # so existe apos a aplicacao
    "presenca",                # so existe apos a aplicacao
]

# Identificadores: não entram como feature, mas servem para agrupar na validação
COLUNAS_ID = ["id_aluno", "id_escola", "id_municipio"]

# ---------------------------------------------------------------------------
# Reprodutibilidade
# ---------------------------------------------------------------------------
SEED = 42
TEST_SIZE = 0.2
VALID_SIZE = 0.2
N_FOLDS = 5

# ---------------------------------------------------------------------------
# Gates — a execução falha quando algum limiar não é atendido
#   Resposta direta ao feedback da Fase 2: separar sem interromper não basta.
# ---------------------------------------------------------------------------
GATES = {
    # % mínimo de registros aprovados na validação de qualidade
    "pct_qualidade_minimo": 90.0,
    # o modelo precisa superar o baseline (classe majoritária) por esta margem
    "ganho_minimo_sobre_baseline": 0.05,
    # ROC-AUC mínimo aceitável para publicar o modelo
    "roc_auc_minimo": 0.60,
    # diferença máxima treino-teste antes de acusar overfitting
    "gap_overfitting_maximo": 0.10,
}

# Faixas válidas para validação de consistência
LIMITES = {
    "proficiencia_saeb": (0.0, 1000.0),
    "indicador_pct": (0.0, 100.0),
    "ano": (2019, 2030),
}
