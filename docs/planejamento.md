# Planejamento — Tech Challenge Fase 3

Registro dos passos do projeto e das decisões analíticas tomadas em cada um.
Cada passo vira uma branch e um Pull Request.

---

## Contexto herdado da Fase 2

A Fase 2 entregou a pipeline de engenharia de dados (Bronze → Silver → Gold) do
Indicador Criança Alfabetizada. A Gold está viva no BigQuery e é o ponto de
partida desta fase.

## Princípios de engenharia

Quatro compromissos que atravessam todos os passos:

| Princípio | Onde aparece |
|---|---|
| Métrica que se calcula, se grava | Passo 7 — resultados em `reports/`, não só na tela |
| A pipeline roda com um comando | Passo 10 — dependências declaradas e execução reproduzível |
| Qualidade que não passa, interrompe | Passo 10 — gates que falham abaixo do limiar |
| Feature que se cria, se usa | Passo 4 — nada calculado fica órfão no caminho |

---

## Decisões analíticas já tomadas

**1. O alvo vem pronto e está equilibrado.**
A coluna `alfabetizado` já existe nos microdados. As classes ficam perto de 50/50,
o que dispensa técnicas de rebalanceamento como primeira escolha e torna a
acurácia uma métrica legível. Ainda assim, ROC-AUC e PR-AUC são as métricas
principais.

**2. `proficiencia` é vazamento e sai da base.**
É a variável que define o alvo. As médias por classe (702,3 contra 779,8) se
separam exatamente no corte de 743. Junto com ela saem `peso_aluno`, `presenca` e
`preenchimento_caderno`, que só existem após a prova aplicada. A regra está em
`config/settings.py`, não espalhada pelo código.

**3. A força preditiva virá do contexto, não do aluno.**
Removido o vazamento, sobram poucas variáveis intrínsecas ao aluno (`rede`,
`caderno`) e `serie` é constante. O sinal precisa vir do município
(indicador, meta e gap da Gold) e de enriquecimento socioeconômico externo. Isso é
consistente com o enunciado, que pede variáveis educacionais, territoriais e
socioeconômicas.

**4. Validação agrupada por município.**
Alunos do mesmo município compartilham contexto. Separar treino e teste
aleatoriamente faria o modelo ver o mesmo município dos dois lados e superestimar
a generalização. A validação usa agrupamento por `id_municipio`.

---

## Passos

- [x] **Passo 1 — Estrutura do repositório + Git**
      Estrutura exigida pelo enunciado, `.gitignore` (com a chave do GCP
      bloqueada), `requirements.txt`, configuração central e README com as 11
      seções mapeadas.

- [x] **Passo 2 — Base analítica**
      Microdados juntados com a Gold da Fase 2 por (`id_municipio`, `ano`, `rede`,
      `serie`), com 99,89% de casamento. Território derivado do código IBGE, o que
      dá cobertura total. 3.867.999 linhas em parquet.

- [x] **Passo 3 — Análise exploratória**
      Distribuições, correlações, ausentes, alvo por UF/região/rede. Figuras em
      `images/`. Fecha com hipóteses analíticas que orientam a modelagem.
      Achados em `reports/analise-exploratoria.md`: o vazamento é exato (100% de
      concordância), 27,3% da classe negativa é ausência e não desempenho, e o
      indicador oficial confunde aprendizagem com participação.

- [x] **Passo 4 — Engenharia de atributos + anti-vazamento**
      A investigação encontrou um segundo vazamento: os agregados da Gold
      (`taxa_municipio`, `gap_municipio`, `atingiu_meta`, `taxa_uf`) são
      calculados no mesmo período, a partir dos próprios alunos a prever.
      Substituídos por versões defasadas de 2023. Agregados por escola foram
      descartados porque o `id_escola` também é reaproveitado entre anos.
      População final: 1.851.852 alunos de 2024. Detalhes em `reports/features.md`.

- [x] **Passo 5 — Pipeline scikit-learn**
      `ColumnTransformer` com imputação de numéricas, encoding de categóricas e
      escala, tudo integrado ao estimador em um único `Pipeline`. As 9 features
      viram 65 colunas. Separação e validação cruzada agrupadas por município,
      com zero territórios em comum entre as partições. Inclui checagem que
      confirma o ajuste restrito ao treino. Detalhes em `reports/pipeline.md`.

- [x] **Passo 6 — Modelagem e otimização**
      Baseline, regressão logística e gradient boosting na mesma validação
      agrupada; o boosting venceu (ROC-AUC 0,6607) e foi otimizado por busca
      aleatória. O gate de acurácia reprovou na primeira execução, o que levou
      ao enriquecimento socioeconômico (IDEB, PIB per capita, população) e à
      medição do teto alcançável. O critério foi revisado com justificativa
      registrada. Resultado final: ROC-AUC 0,6604 no teste, com os três gates
      aprovados. Detalhes em `reports/modelagem.md`.

- [ ] **Passo 7 — Avaliação**
      ROC-AUC, PR-AUC, precisão, recall, F1, matriz de confusão, calibração e
      curvas de aprendizado. Métricas gravadas em `reports/`, não só exibidas.

- [ ] **Passo 8 — Interpretabilidade**
      Permutation Importance e SHAP. Responde "quais fatores mais impactam a
      alfabetização".

- [ ] **Passo 9 — Aplicação estratégica**
      Escore de risco por município, agrupamento de regiões com padrão
      semelhante e projeção de quem tende a não atingir a meta de 2030.

- [ ] **Passo 10 — Orquestração + gates**
      Um comando roda a pipeline inteira. A execução falha quando a qualidade
      cai abaixo do limiar ou o modelo não supera o baseline.

- [ ] **Passo 11 — README, documentação e vídeo**
      Fechar as 11 seções do README, a documentação técnica e o vídeo executivo
      de até 5 minutos.
