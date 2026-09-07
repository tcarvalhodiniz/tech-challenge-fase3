# Engenharia de atributos e tratamento de vazamento

Este passo define o conjunto que vai para o modelo. A maior parte do trabalho foi
decidir o que tirar, não o que criar.

---

## 1. Um segundo vazamento, menos óbvio que o primeiro

A análise exploratória tratou do vazamento evidente: a `proficiencia` define o alvo.
Ao montar as features apareceu um caso mais sutil.

O `taxa_municipio` que veio da Gold é a taxa de alfabetização do município **naquele
mesmo ano**, calculada a partir dos mesmos alunos que se quer prever. Cada aluno
contribui para o valor da variável que vai prevê-lo. E, como a taxa só existe depois
que todos fizeram a prova, ela não estaria disponível no momento em que a predição
teria valor. É o mesmo problema da proficiência, em escala agregada.

O `gap_municipio` e o `atingiu_meta` derivam dessa taxa, então herdam o problema. O
`taxa_uf` é o mesmo caso, um nível acima.

A correção foi substituir esses agregados por versões calculadas com os dados de
2023. Custa sinal, mas o que sobra é honesto:

| Variável | Correlação com o alvo |
|---|---|
| Taxa do município no mesmo ano (vazada) | +0,319 |
| Taxa do município no ano anterior | +0,269 |

Como as features defasadas exigem um ano anterior, a população modelada passa a ser
a de 2024, com o contexto de 2023.

## 2. Agregados por escola foram descartados

A intenção era usar a taxa da escola no ano anterior, esperando mais sinal por ser
uma unidade mais granular que o município. O resultado foi o oposto: correlação de
+0,100 contra +0,269 do município.

A hipótese inicial foi ruído de amostra pequena, já que a escola tem 41 alunos em
média. Exigir um mínimo de 40 alunos não mudou nada, a correlação ficou em +0,094.

O motivo é outro. Das 36.051 escolas presentes nos dois anos, **35.187 (97,6%)
aparecem em municípios diferentes**. O `id_escola` é reaproveitado entre anos, do
mesmo modo que o `id_aluno`. A taxa "da escola" estava casando escolas que não são a
mesma.

O único identificador estável é o `id_municipio`, que é o código IBGE.

## 3. Partida a frio como informação

Dos alunos de 2024, 76,8% têm município com histórico em 2023. Os 23,2% restantes
não são um defeito da base: representam o caso real de um território sem medição
anterior.

Em vez de imputar um valor e apagar o fato, a coluna `sem_historico_municipio`
registra a situação explicitamente. O modelo pode aprender que a ausência de
histórico é, ela própria, um sinal.

Municípios com menos de 10 alunos avaliados em 2023 também ficam sem taxa defasada,
porque abaixo disso o agregado é instável.

## 4. Conjunto final

**População:** 1.851.852 alunos, ano de 2024, com prova aplicada, em 5.517
municípios. Alvo positivo em 59,78%.

| Feature | Origem | Cobertura |
|---|---|---|
| `rede` | aluno | 100% |
| `caderno` | aluno | 100% |
| `sigla_uf` | código IBGE | 100% |
| `regiao` | código IBGE | 100% |
| `sem_historico_municipio` | derivada | 100% |
| `meta_municipio` | Gold, meta de política | 84,7% |
| `taxa_municipio_ant` | agregado de 2023 | 76,8% |
| `alunos_municipio_ant` | agregado de 2023 | 76,8% |
| `taxa_uf_ant` | agregado de 2023 | 76,9% |

A `meta_municipio` permanece porque é uma meta de política definida com
antecedência, não um resultado medido. Não depende do desfecho dos alunos.

## 5. Exclusões

| Categoria | Colunas | Motivo |
|---|---|---|
| Vazamento direto | `proficiencia`, `peso_aluno`, `presenca`, `preenchimento_caderno` | determinam o alvo |
| Agregado do mesmo período | `taxa_municipio`, `gap_municipio`, `atingiu_meta`, `taxa_uf` | calculados a partir dos alunos a prever |
| Identificador instável | `id_aluno`, `id_escola` | reaproveitados entre anos |
| Sem uso | `serie`, `ano`, `meta_uf`, `gap_uf`, `rede_desc` | constantes, nulas ou redundantes |

As listas estão em `config/settings.py` e são aplicadas pelo módulo, não por
descarte manual.

## 6. Auditoria

Nenhuma feature restante prevê o alvo isoladamente com acerto quase perfeito, que
seria o sintoma de vazamento remanescente. O valor mais alto é o da `sigla_uf`, em
0,853, e corresponde a desigualdade regional real: existem estados em que a maioria
dos alunos está de um lado do corte.

## 7. O que fica em aberto

O `caderno` continua no conjunto sem avaliação individual. Ele identifica a versão
da prova aplicada e, em tese, a atribuição deveria ser aleatória. Se for, não carrega
sinal e sairá na seleção de features. Se não for, indica algo sobre a aplicação que
merece investigação.
