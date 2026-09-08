# Pipeline de pré-processamento

Este passo monta a estrutura que leva os dados até o estimador. O modelo em si vem
no passo seguinte; aqui o que importa é garantir que nenhuma informação do teste
chegue ao treino.

---

## 1. Por que tudo fica dentro de um único Pipeline

O enunciado pede a integração do pré-processamento diretamente ao modelo. Não é
questão de organização de código.

Um `StandardScaler` ajustado antes da separação aprende a média do conjunto
inteiro, teste incluído. Essa média entra depois no treino disfarçada de
transformação, e o desempenho medido fica otimista sem que nada no código pareça
errado. O mesmo vale para a imputação: a mediana usada para preencher faltantes não
pode ter sido calculada com dados que o modelo não deveria conhecer.

Dentro do `Pipeline`, cada `fit` só enxerga a partição de treino daquele fold.

## 2. Transformações por tipo de variável

| Tipo | Colunas | Tratamento |
|---|---|---|
| Numéricas | `taxa_municipio_ant`, `alunos_municipio_ant`, `taxa_uf_ant`, `meta_municipio` | imputação pela mediana com indicador de ausência, depois padronização |
| Categóricas | `rede`, `caderno`, `sigla_uf`, `regiao` | imputação pela moda, depois one-hot |
| Binária | `sem_historico_municipio` | passa direto |

A mediana foi escolhida no lugar da média por ser robusta a distribuições
assimétricas, o que é o caso de `alunos_municipio_ant`.

O `add_indicator` mantém registro de qual valor estava ausente. Como a falta aqui é
sistemática, e não aleatória, apagá-la com imputação descartaria informação real:
município sem histórico e meta inexistente para o par ano-rede são situações
distintas de um valor simplesmente desconhecido.

O `handle_unknown="ignore"` no one-hot cobre o caso de um município de teste trazer
uma categoria que não apareceu no treino. Sem isso, a predição quebraria.

As 9 features viram **65 colunas** depois da expansão categórica.

## 3. Separação agrupada por município

Alunos do mesmo município compartilham escola, gestão e contexto socioeconômico.
Uma separação aleatória colocaria o mesmo território dos dois lados, e o modelo
poderia reconhecer o município em vez de generalizar para territórios que nunca viu.
Como a aplicação prática é justamente estimar risco em municípios ainda não
medidos, o agrupamento reproduz a pergunta real.

A primeira versão usava `GroupShuffleSplit`, que agrupa mas não estratifica. O
resultado foi um desequilíbrio de mais de dois pontos na proporção de alfabetizados:

| Divisor | Alvo positivo no treino | Alvo positivo no teste |
|---|---|---|
| `GroupShuffleSplit` | 59,33% | 61,88% |
| `StratifiedGroupKFold` | 59,79% | 59,78% |

Como os municípios têm taxas muito diferentes entre si, sortear grupos sem
estratificar desloca o alvo. A troca por um fold do `StratifiedGroupKFold` resolve
agrupamento e estratificação ao mesmo tempo.

**Partição final:** 1.494.345 alunos de 4.353 municípios no treino e 357.507 alunos
de 1.164 municípios no teste, com zero municípios em comum.

**Validação cruzada:** 5 folds pelo mesmo critério, todos com zero municípios
compartilhados entre treino e teste.

## 4. Verificação de vazamento

A pipeline inclui uma checagem que compara a estatística aprendida pelo
pré-processador com a estatística do conjunto inteiro. Se fossem iguais, o ajuste
teria enxergado o teste.

| Coluna | Média aprendida no treino | Média do conjunto inteiro |
|---|---|---|
| `taxa_municipio_ant` | 58,5185 | 58,2479 |
| `alunos_municipio_ant` | 3256,3569 | 2920,9073 |
| `taxa_uf_ant` | 58,7301 | 58,5833 |
| `meta_municipio` | 59,8644 | 59,8175 |

A primeira versão da checagem usava a mediana do imputador, e duas colunas davam
valores idênticos. Não era vazamento: `taxa_uf_ant` tem apenas 92 valores distintos,
um por par UF-rede, e a mediana é estável demais para se mover. A média do
`StandardScaler` é contínua e sensível a qualquer mudança na amostra, o que torna a
leitura inequívoca.

Vale registrar que o teste é unidirecional. Uma diferença prova que o ajuste ficou
restrito ao treino; uma coincidência não prova o contrário.

## 5. O que fica para o passo seguinte

A pipeline está pronta para receber qualquer estimador via `construir_pipeline()`.
O passo de modelagem começa pelo baseline da classe majoritária e pela regressão
logística, antes de partir para modelos de árvore.
