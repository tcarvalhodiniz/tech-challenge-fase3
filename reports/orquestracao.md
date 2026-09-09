# Orquestração e gates

Até aqui cada etapa era um módulo executado à mão, na ordem que estivesse
documentada. Este passo transforma isso num comando único, com dependências
declaradas e dois pontos onde a execução para se o resultado não for aceitável.

---

## 1. Um comando

```bash
GOOGLE_APPLICATION_CREDENTIALS=chave.json python -m src.pipeline
```

Nove etapas, com o que cada uma exige e produz declarado no código:

| # | Etapa | Requer | Produz | Gate |
|---|---|---|---|---|
| 1 | `base_analitica` | BigQuery | `base_analitica.parquet` | |
| 2 | `enriquecimento` | BigQuery | `externo_municipio.parquet` | |
| 3 | `features` | base analítica | `base_modelagem.parquet` | |
| 4 | `qualidade` | base de modelagem | `quarentena.parquet` | **sim** |
| 5 | `treino` | base de modelagem | `modelo.joblib` | **sim** |
| 6 | `avaliacao` | modelo | figuras e métricas | |
| 7 | `interpretabilidade` | modelo | figuras e métricas | |
| 8 | `aplicacao` | modelo, BigQuery | `risco_municipio.parquet` | |
| 9 | `publicar_gold` | base, BigQuery | tabelas na Gold | |

Cada etapa confere se suas entradas existem antes de começar, e etapas cujos
artefatos já estão materializados são puladas. `--do-inicio` refaz tudo;
`--somente-local` pula o que depende do BigQuery.

Execução completa em 211 segundos com os artefatos presentes. O registro de cada
rodada fica em `reports/execucao_pipeline.json`, com situação e tempo por etapa,
o que permite comparar execuções.

## 2. O gate de qualidade, que estava declarado sem uso

O limiar `pct_qualidade_minimo` de 90% existia em `config/settings.py` desde o
primeiro commit e nunca havia sido aplicado. Um dos princípios declarados no
planejamento é que nada calculado fica órfão, e o próprio gate estava violando isso.

A validação aplica seis regras sobre a base de modelagem e separa os reprovados em
quarentena, com o motivo anexado:

| Regra | O que reprova |
|---|---|
| `alvo_ausente` | linha sem desfecho |
| `alvo_fora_do_dominio` | alvo diferente de 0 ou 1 |
| `municipio_malformado` | código IBGE que não tem sete dígitos |
| `*_fora_da_faixa` | taxa, meta ou aprovação fora de 0 a 100 |
| `ideb_fora_da_escala` | IDEB fora de 0 a 10 |

Na base atual nenhuma regra é violada e a qualidade fica em 100%.

### Verificação de que o gate funciona

Um gate que nunca reprovou não está demonstrado. A checagem injeta taxas
impossíveis, acima de 100%, em proporções crescentes:

| Base | Qualidade | Resultado |
|---|---|---|
| Intacta | 100,00% | passou |
| 5% corrompida | 95,00% | passou |
| 15% corrompida | 85,00% | **interrompeu** |

A quarentena também preserva o diagnóstico. Ao corromper duas colunas diferentes,
os motivos aparecem separados e combinados:

```
taxa_municipio_ant_fora_da_faixa                          199
municipio_malformado                                       99
municipio_malformado; taxa_municipio_ant_fora_da_faixa      1
```

A linha com dois problemas registra os dois. Contar reprovações sem o motivo diria
que algo está errado sem dizer o quê.

## 3. O gate de desempenho

O treino já carregava os seus, verificados no passo de modelagem:

| Gate | Limiar | Obtido |
|---|---|---|
| ROC-AUC mínimo | 0,60 | 0,6604 |
| Captura mínima do teto | 0,75 | 0,8429 |
| Gap de overfitting | 0,10 | 0,0134 |

Quando algum reprova, a etapa levanta erro e a orquestração interrompe a execução
antes de publicar qualquer coisa. Foi o que aconteceu na primeira rodada do Passo 6,
e a interrupção levou à investigação do teto alcançável.

## 4. Comportamento diante de falha

A pipeline para na etapa que falhou, informa o tipo do erro e a mensagem, grava o
registro parcial e sai com código 1. Um exemplo real, ocorrido enquanto este passo
era testado numa branch sem os módulos dos passos anteriores:

```
XX  interpretabilidade    ModuleNotFoundError: No module named 'src.evaluation.interpretabilidade'
PIPELINE INTERROMPIDA em 'interpretabilidade'
```

Etapas cujas entradas não existem são marcadas como bloqueadas em vez de falharem,
já que a causa é diferente: não é erro de execução, é dependência ausente.
