# Predição e Inteligência Analítica para Alfabetização no Brasil
> **Pós-Graduação em AI Scientist – FIAP** · Tech Challenge – Fase 3

Modelo supervisionado que prevê se uma criança será considerada **alfabetizada**
ao final do 2º ano do ensino fundamental, a partir de variáveis educacionais,
territoriais e socioeconômicas. Os dados partem da **camada Gold** construída no
Tech Challenge da Fase 2.

---

## 1. Contexto do problema

O **Compromisso Nacional Criança Alfabetizada** estabelece que toda criança deve
estar alfabetizada ao final do 2º ano do ensino fundamental. A *Pesquisa Alfabetiza
Brasil* (INEP, 2023) fixou o **ponto de corte de 743 pontos** na escala Saeb: a
partir dele a criança é considerada alfabetizada. A meta nacional é atingir **80%
até 2030**.

Conhecer o indicador atual, porém, não basta. Gestores públicos precisam
**antecipar risco** — saber onde a alfabetização tende a falhar antes que o
resultado apareça — e entender **quais fatores pesam mais** nesse desfecho. É esse
o espaço que a Ciência de Dados ocupa aqui: transformar dado público em decisão.

## 2. Objetivo analítico

Prever, no grão do aluno, o desfecho binário **alfabetizado / não alfabetizado**,
e a partir do modelo responder:

- Quais fatores mais impactam a alfabetização?
- Quais municípios apresentam maior risco educacional?
- Quais regiões possuem padrões semelhantes?
- Como prever municípios que podem não atingir as metas futuras?

O foco não é maximizar métrica, e sim produzir inteligência aplicável à política
pública.

## 3. Descrição da base utilizada

**Grão:** aluno. **Período:** 2023 e 2024.

| Fonte | Origem | Volume |
|---|---|---|
| Microdados de alunos | `basedosdados.br_inep_avaliacao_alfabetizacao.alunos` | 3.867.999 alunos |
| `indicador_municipio` | Gold da Fase 2 (BigQuery) | 23.995 linhas |
| `evolucao_municipio` | Gold da Fase 2 (BigQuery) | 61.459 linhas |
| `indicador_uf` | Gold da Fase 2 (BigQuery) | 145 linhas |

**Alvo (`alfabetizado`).** Vem pronto nos microdados e é derivado do corte de 743
pontos. As classes estão praticamente equilibradas:

| Ano | Não alfabetizados | Alfabetizados |
|---|---|---|
| 2023 | 870.012 | 877.427 |
| 2024 | 1.013.441 | 1.107.119 |

**Chaves de integração:** `id_municipio`, `ano`, `rede`, `serie`.

> Enriquecimento externo previsto (IBGE, Atlas do Desenvolvimento Humano) —
> documentado na seção de modelagem quando aplicado.

### Tratamento de data leakage

A coluna **`proficiencia` define o alvo** (`alfabetizado = proficiencia >= 743`) —
as médias por classe são 702,3 e 779,8, separadas exatamente no corte. Mantê-la
como preditora produziria acerto perfeito e um modelo sem utilidade prática.

Ficam fora do conjunto de treino, por só existirem **depois** da prova aplicada —
ou seja, informação indisponível no momento em que a predição teria valor:

| Coluna | Motivo da exclusão |
|---|---|
| `proficiencia` | define o alvo diretamente |
| `peso_aluno` | peso amostral atribuído após a prova |
| `presenca` | só existe após a aplicação |
| `preenchimento_caderno` | só existe após a aplicação |

A regra está declarada em [`config/settings.py`](config/settings.py) e é aplicada
pela pipeline, não manualmente.

## 4. Etapas de modelagem

_A preencher — Passos 4 a 6 do [planejamento](docs/planejamento.md)._

## 5. Escolha do algoritmo

_A preencher — Passo 6._

## 6. Métricas de avaliação

_A preencher — Passo 7._

## 7. Interpretação dos resultados

_A preencher — Passo 8 (Feature Importance e SHAP)._

## 8. Insights encontrados

_A preencher — Passo 9._

## 9. Limitações do projeto

_A preencher._

## 10. Aplicação prática para políticas públicas

_A preencher — Passo 9._

## 11. Possíveis evoluções futuras

_A preencher._

---

## Estrutura do repositório

```
tech-challenge-fase3/
├── config/            # configuração central (fontes, anti-vazamento, gates)
├── data/              # camadas locais (não versionado)
│   ├── raw/           # extração bruta do BigQuery
│   └── processed/     # base analítica pronta para modelagem
├── notebooks/         # EDA e experimentação
├── src/
│   ├── preprocessing/ # construção da base e transformações
│   ├── modeling/      # treino, tuning e pipeline do modelo
│   ├── evaluation/    # métricas, validação e gates
│   └── visualization/ # gráficos e material de apoio
├── reports/           # métricas persistidas e relatórios
├── images/            # figuras geradas pela análise
└── docs/              # planejamento e decisões analíticas
```

## Como executar

**Pré-requisitos**
- Python 3.10+ e as dependências de [`requirements.txt`](requirements.txt).
- Projeto GCP com acesso ao BigQuery e uma *service account* (papéis BigQuery User
  + Job User). A chave JSON fica **fora** do repositório.

```bash
pip install -r requirements.txt
export GOOGLE_APPLICATION_CREDENTIALS=/caminho/para/chave.json
```

_Comando único da pipeline: a preencher no Passo 10._

---

## Autor

**Thiago Corrêa Carvalho Diniz** — RM 371212

Pós-Graduação AI Scientist — FIAP
