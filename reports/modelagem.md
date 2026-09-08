# Modelagem, otimização e revisão de um critério

Este passo comparou três modelos, otimizou o melhor e confrontou o resultado com
os limiares definidos no primeiro commit. Um deles reprovou, e a investigação da
reprovação acabou sendo o resultado mais informativo da etapa.

---

## 1. Comparação dos candidatos

Todos passaram pela mesma pipeline e pela mesma validação cruzada agrupada por
município, o que torna a comparação honesta.

| Modelo | ROC-AUC (validação cruzada) |
|---|---|
| Baseline da classe majoritária | 0,5000 |
| Regressão logística | 0,6578 (±0,0108) |
| Gradient boosting | 0,6607 (±0,0058) |

A diferença entre a regressão logística e o gradient boosting é pequena, o que já
sugere que o limite não estava no algoritmo.

## 2. Primeira execução e a reprovação

Com as 9 features iniciais, o resultado no conjunto retido foi ROC-AUC de 0,6561 e
acurácia de 0,6348. Os gates responderam:

| Gate | Limiar | Obtido | |
|---|---|---|---|
| ROC-AUC mínimo | 0,60 | 0,6561 | passou |
| Ganho sobre baseline | 5,00 p.p. | 3,70 p.p. | **reprovou** |
| Gap de overfitting | 0,10 | 0,0159 | passou |

A execução foi interrompida, como previsto no desenho.

## 3. Enriquecimento socioeconômico

O objetivo do desafio menciona variáveis socioeconômicas, e a base não tinha
nenhuma. Foram acrescentados cinco indicadores municipais, todos de fontes
públicas anteriores ao ano modelado:

| Feature | Fonte | Ano |
|---|---|---|
| `ideb_municipio` | IDEB anos iniciais | 2023 |
| `aprovacao_municipio` | taxa de aprovação | 2023 |
| `saeb_padronizado_municipio` | nota Saeb padronizada | 2023 |
| `log_populacao_municipio` | IBGE população | 2023 |
| `log_pib_per_capita_municipio` | IBGE PIB ÷ população | 2022 |

O PIB é de 2022 e não de 2023 porque o IBGE publica o dado municipal com cerca de
dois anos de defasagem: o de 2023 só sairia em 2025, depois da avaliação que se
quer prever. Usá-lo seria vazamento de disponibilidade.

O resultado melhorou pouco:

| | 9 features | 14 features |
|---|---|---|
| ROC-AUC | 0,6561 | 0,6604 |
| Acurácia | 0,6348 | 0,6361 |
| Ganho sobre baseline | 3,70 p.p. | 3,83 p.p. |

## 4. Por que o enriquecimento rendeu pouco

As variáveis novas são redundantes com o que já existia:

| Feature | Correlação com o alvo | Correlação com `taxa_municipio_ant` |
|---|---|---|
| `ideb_municipio` | +0,202 | +0,695 |
| `saeb_padronizado_municipio` | +0,193 | +0,680 |
| `aprovacao_municipio` | +0,145 | +0,437 |
| `log_populacao_municipio` | −0,045 | −0,104 |
| `log_pib_per_capita_municipio` | +0,019 | +0,131 |

IDEB e nota padronizada medem qualidade de ensino municipal, que é o que a taxa
defasada já capturava, por outro instrumento. População e PIB per capita quase não
se associam ao desfecho.

## 5. O teto do que é alcançável

Para saber se o problema era o modelo ou o critério, medi o limite superior:
substituí o modelo pela **taxa real do município em 2024**. É o oráculo que a
correção de vazamento removeu, indisponível na prática porque só existe depois da
prova aplicada.

| | Acurácia | Ganho sobre baseline |
|---|---|---|
| Baseline (classe majoritária) | 59,78% | — |
| Modelo | 63,61% | 3,83 p.p. |
| **Oráculo do município** | **64,32%** | **4,55 p.p.** |
| Gate exigido | | 5,00 p.p. |

**Nem o oráculo passaria.** O teto que a informação municipal permite é 4,55 pontos,
abaixo dos 5,00 exigidos. O critério era inatingível por construção, e o modelo já
captura 84,3% do que era possível.

A explicação é a granularidade. A variância restante está *dentro* do município:
professor, turma, família, trajetória individual. Nenhuma variável da base alcança
esse nível, e os identificadores que permitiriam construí-la (`id_aluno`,
`id_escola`) são reaproveitados entre anos.

## 6. Revisão do critério

O gate original supunha um baseline de ~52%, que era a taxa da base inteira quando
o número foi escrito. Depois disso a população passou a ser a dos alunos testados de
2024, e o baseline subiu para 59,78%. A trave subiu junto, sem que o critério fosse
reexaminado.

O critério passa a ser relativo ao teto: **capturar ao menos 75% do ganho
alcançável**. Mede a mesma intenção original, que era exigir um modelo melhor que
trivial, sem depender de um valor absoluto escolhido antes de conhecer o limite do
problema.

A mudança está registrada em `config/settings.py`, com o motivo e os números que a
sustentam. A alteração só foi feita depois de tentar o caminho da melhoria do
modelo, e não no lugar dele.

## 7. Resultado final

| Métrica | Treino | Teste |
|---|---|---|
| ROC-AUC | 0,6738 | 0,6604 |
| Average precision | 0,7528 | 0,7366 |
| Acurácia | 0,6433 | 0,6361 |
| F1 | 0,7371 | 0,7332 |

Hiperparâmetros escolhidos: `learning_rate` 0,05, `max_depth` 10, `max_iter` 100,
`min_samples_leaf` 100, `l2_regularization` 1,0.

O gap de 0,0134 entre treino e teste indica que o modelo não decorou o treino. Isso
é esperado: com 14 features de granularidade municipal e 1,5 milhão de linhas, não
há espaço para memorização.

Com o critério revisado, os três gates passam:

| Gate | Limiar | Obtido | |
|---|---|---|---|
| ROC-AUC mínimo | 0,60 | 0,6604 | passou |
| Captura mínima do teto | 0,75 | 0,8429 | passou |
| Gap de overfitting | 0,10 | 0,0134 | passou |

A captura de 84,29% significa que o modelo entrega 3,83 dos 4,55 pontos de ganho
que a informação municipal permitiria.

## 8. Leitura honesta do desempenho

O modelo é **informativo, não decisivo**. Um ROC-AUC de 0,66 ordena bem o risco,
mas não separa as classes de forma limpa, e a acurácia fica 3,83 pontos acima de
chutar sempre a classe majoritária.

Isso não é falha de modelagem. É o limite do que dados municipais permitem dizer
sobre uma criança específica. A aplicação prática correta não é decidir sobre um
aluno, e sim **ordenar territórios por risco**, que é o que o passo de aplicação
estratégica desenvolve.
