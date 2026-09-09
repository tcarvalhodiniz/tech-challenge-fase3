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
    "indicador_municipio": "meta x realizado por município, com gap",
    "evolucao_municipio": "trajetória do indicador rumo a 2030",
    "indicador_uf": "meta x realizado por UF",
}

BD_PROJECT = "basedosdados"
BD_DATASET = "br_inep_avaliacao_alfabetizacao"
TABELA_MICRODADOS = "alunos"  # ~3,87 milhões de alunos (2023-2024)

# ---------------------------------------------------------------------------
# Semântica de negócio
# ---------------------------------------------------------------------------
# Ponto de corte de proficiência do Saeb (Alfabetiza Brasil 2023)
PONTO_CORTE_SAEB = 743
ALVO = "alfabetizado"  # 0 = não alfabetizado, 1 = alfabetizado

# ---------------------------------------------------------------------------
# Anti-vazamento (data leakage)
#   `proficiencia` DEFINE o alvo (alfabetizado = proficiencia >= 743).
#   Mantê-la como feature daria acerto perfeito e modelo inútil. As demais só
#   existem depois da prova aplicada — informação indisponível no momento da
#   predição. Todas ficam fora do conjunto de treino.
# ---------------------------------------------------------------------------
COLUNAS_VAZAMENTO = [
    "proficiencia",            # define o alvo diretamente
    "peso_aluno",              # peso amostral pós-prova
    "preenchimento_caderno",   # só existe após a aplicação
    "presenca",                # só existe após a aplicação
]

# Agregados do mesmo período. São calculados a partir dos próprios alunos que se
# quer prever e só existem depois que todos fizeram a prova. É o mesmo vazamento
# da proficiência, em escala agregada. As versões defasadas substituem estas.
COLUNAS_AGREGADO_MESMO_PERIODO = [
    "taxa_municipio",          # taxa do município no próprio ano
    "gap_municipio",           # derivado da taxa do próprio ano
    "atingiu_meta",            # derivado da taxa do próprio ano
    "taxa_uf",                 # taxa da UF no próprio ano
]

# Identificadores anonimizados. A própria fonte descreve `id_escola` como
# "Máscara do código da escola (códigos fictícios)", e o comportamento de
# `id_aluno` é o mesmo: o código é reatribuído a cada edição, então aparece em
# municípios diferentes de um ano para o outro e não acompanha a mesma entidade.
# Só o id_municipio é estável, por ser o código IBGE de 7 dígitos.
COLUNAS_ID_INSTAVEL = ["id_aluno", "id_escola"]

# Sem variação, sem dado ou redundantes
COLUNAS_SEM_USO = [
    "serie",                   # constante: todos no 2º ano
    "meta_uf", "gap_uf",       # 100% nulas (meta por UF só existe para rede 5)
    "rede_desc",               # redundante com `rede`
]

# Identificador estável, usado para agrupar a validação
COLUNA_GRUPO = "id_municipio"

# ---------------------------------------------------------------------------
# Reprodutibilidade
# ---------------------------------------------------------------------------
SEED = 42
TEST_SIZE = 0.2
VALID_SIZE = 0.2
N_FOLDS = 5

# ---------------------------------------------------------------------------
# Gates — a execução falha quando algum limiar não é atendido
#   Um limiar definido depois de ver o resultado não é gate, é carimbo. Estes
#   valem como compromisso assumido antes: mudá-los exige justificar o porquê.
# ---------------------------------------------------------------------------
GATES = {
    # % mínimo de registros aprovados na validação de qualidade
    "pct_qualidade_minimo": 90.0,
    # ROC-AUC mínimo aceitável para publicar o modelo
    "roc_auc_minimo": 0.60,
    # diferença máxima treino-teste antes de acusar overfitting
    "gap_overfitting_maximo": 0.10,
    # fração mínima do ganho de acurácia que o modelo precisa capturar
    "captura_minima_do_teto": 0.75,
}

# Registro da revisão de um gate
#
# O critério original era "ganho_minimo_sobre_baseline": 0.05, ou seja, cinco
# pontos de acurácia acima da classe majoritária. Foi definido no primeiro commit
# supondo baseline de ~52%, que era a taxa positiva da base inteira.
#
# Duas coisas mudaram depois. A população passou a ser a dos alunos testados de
# 2024, o que elevou o baseline para 59,78%, e a granularidade disponível ficou
# restrita ao município, já que id_aluno e id_escola são reaproveitados entre anos.
#
# A medição do teto mostrou que o critério era inatingível. Substituindo o modelo
# pela taxa real do município no próprio ano — o oráculo que a correção de
# vazamento removeu e que nenhum modelo honesto pode ter — a acurácia chega a
# 64,32% no conjunto de teste, um ganho de 4,55 pontos. Menos que os 5,00
# exigidos. Nenhum modelo passaria, porque a variância restante está dentro do
# município e não há variável na base que a alcance.
#
# O critério passa a ser relativo ao que é alcançável: capturar ao menos 75% do
# ganho que a informação municipal permite. Mede a mesma intenção original sem
# depender de um número escolhido antes de conhecer o teto.

# Faixas válidas para validação de consistência
LIMITES = {
    "proficiencia_saeb": (0.0, 1000.0),
    "indicador_pct": (0.0, 100.0),
    "ano": (2019, 2030),
}
