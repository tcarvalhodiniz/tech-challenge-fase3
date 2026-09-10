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

Conhecer o indicador atual, porém, não basta. Gestores públicos precisam antecipar
risco, ou seja, saber onde a alfabetização tende a falhar antes que o resultado
apareça, e entender quais fatores pesam mais nesse desfecho. É esse o espaço que a
Ciência de Dados ocupa aqui: transformar dado público em decisão.

## 2. Objetivo analítico

Prever, no grão do aluno, o desfecho binário **alfabetizado / não alfabetizado**,
e a partir do modelo responder:

- Quais fatores mais impactam a alfabetização?
- Quais municípios apresentam maior risco educacional?
- Quais regiões possuem padrões semelhantes?
- Como prever municípios que podem não atingir as metas futuras?

O objetivo é produzir inteligência aplicável à política pública, e a métrica
serve a esse propósito.

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

### Relação com a camada Gold da Fase 2

A Gold da Fase 2 foi construída para responder a uma pergunta de acompanhamento:
*como cada município está em relação à sua meta*. É uma pergunta de relatório, no
grão de município. Esta fase pergunta *se uma criança será alfabetizada*, que é
outra pergunta e outro grão.

Das 14 variáveis do modelo final, apenas uma vem da Gold:

| Origem | Variáveis |
|---|---|
| Microdados do Alfabetiza Brasil | 8 |
| Fontes públicas externas (IDEB, IBGE) | 5 |
| Gold da Fase 2 | 1 (`meta_municipio`) |

O motivo é o tratamento de vazamento, que removeu as demais colunas da Gold.
As colunas `taxa_municipio`, `gap_municipio`, `atingiu_meta` e `taxa_uf` são
agregados calculados **no mesmo período** que o alvo, a partir dos próprios alunos
que se quer prever, e só existem depois da prova aplicada. `meta_uf` e `gap_uf`
chegam 100% nulas. Sobra a meta municipal, que é alvo de política definido com
antecedência e não resultado medido.

A observação que decorre disso: o que qualifica a Gold para relatório é o que a
desqualifica para predição. O `taxa_realizada` é a métrica que faz dela uma boa
tabela de acompanhamento e é exatamente o vazamento que invalida um modelo. Uma
camada analítica é construída para um propósito, e uma Gold de BI não é
automaticamente reaproveitável para aprendizado de máquina.

O contexto municipal que o modelo usa foi então reconstruído a partir dos
microdados de 2023, com um ano de defasagem, e complementado por indicadores
socioeconômicos externos.

### Tratamento de data leakage

A coluna `proficiencia` define o alvo (`alfabetizado = proficiencia >= 743`). As
médias por classe são 702,3 e 779,8, separadas exatamente no corte. Mantê-la como
preditora produziria acerto perfeito e um modelo sem utilidade prática.

As colunas abaixo ficam fora do conjunto de treino porque só existem depois da
prova aplicada, quando a predição já não teria valor:

| Coluna | Motivo da exclusão |
|---|---|
| `proficiencia` | define o alvo diretamente |
| `peso_aluno` | peso amostral atribuído após a prova |
| `presenca` | só existe após a aplicação |
| `preenchimento_caderno` | só existe após a aplicação |

A regra está declarada em [`config/settings.py`](config/settings.py) e é aplicada
pela pipeline, sem intervenção manual.

## 4. Etapas de modelagem

### Análise exploratória

Relatório completo em [`reports/analise-exploratoria.md`](reports/analise-exploratoria.md);
o percurso da análise, em [`notebooks/01_analise_exploratoria.ipynb`](notebooks/01_analise_exploratoria.ipynb).

Três achados definem o desenho do modelo.

O primeiro é que a concordância entre `proficiencia >= 743` e o alvo é de 100%: a
proficiência máxima da classe negativa é 742,999819 e a mínima da positiva é 743.
Não existe linha fora do padrão. O mesmo cruzamento mostrou que todo aluno ausente
está classificado como não alfabetizado, o que torna `presenca` e
`preenchimento_caderno` igualmente determinantes.

O segundo veio dessa descoberta. Dos 1.883.453 alunos não alfabetizados, 513.338
(27,3%) nunca fizeram a prova. Como as variáveis que sinalizam ausência são as
excluídas por vazamento, esses registros entrariam no treino sem sinal aprendível,
e por isso a modelagem usa apenas a população testada.

O terceiro é que separar aprendizagem de participação reordena as regiões. O Sul sai
de 52,5% (3º lugar) no indicador oficial para 64,5% (1º lugar) entre os testados,
porque tem a maior ausência do país, de 18,5%. O Nordeste apresenta o quadro oposto:
desempenho abaixo da média com a maior participação. São problemas distintos e pedem
respostas de política pública distintas.

### Engenharia de atributos

Relatório em [`reports/features.md`](reports/features.md).

Ao montar as variáveis apareceu um segundo vazamento, menos óbvio que o da
proficiência. O `taxa_municipio` vindo da Gold é a taxa do município **naquele
mesmo ano**, calculada a partir dos mesmos alunos que se quer prever, e só existe
depois que todos fizeram a prova. `gap_municipio`, `atingiu_meta` e `taxa_uf`
derivam da mesma medição e herdam o problema.

A correção substituiu esses agregados por versões calculadas com dados de 2023. A
correlação com o alvo cai de +0,319 para +0,269, mas o que sobra existe no momento
da predição. Como isso exige um ano anterior, a população modelada passa a ser a de
2024 com contexto de 2023: **1.851.852 alunos em 5.517 municípios**.

Agregados por escola foram testados e descartados. A taxa da escola no ano anterior
rendeu correlação de apenas +0,100, e a causa não era amostra pequena: das 36.051
escolas presentes nos dois anos, 35.187 aparecem em municípios diferentes. A fonte
descreve `id_escola` como *"Máscara do código da escola (códigos fictícios)"*. É um
identificador anonimizado, reatribuído a cada edição. O mesmo vale para `id_aluno`.
Só o `id_municipio` é estável, por ser o código IBGE.

### Pipeline

Relatório em [`reports/pipeline.md`](reports/pipeline.md).

Imputação pela mediana com indicador de ausência, codificação one-hot e
padronização, tudo dentro de um `Pipeline` único junto ao estimador. As 9 variáveis
originais viram 65 colunas.

A separação e a validação cruzada são agrupadas por município, para que o modelo
seja avaliado em territórios que nunca viu. É a pergunta real: estimar risco onde
ainda não houve medição. Todas as partições saem com zero municípios em comum.

## 5. Escolha do algoritmo

Relatório em [`reports/modelagem.md`](reports/modelagem.md).

Três candidatos na mesma validação cruzada agrupada:

| Modelo | ROC-AUC |
|---|---|
| Baseline da classe majoritária | 0,5000 |
| Regressão logística | 0,6578 (±0,0108) |
| **Gradient boosting** | **0,6607** (±0,0058) |

O gradient boosting venceu e foi otimizado por busca aleatória sobre cinco
hiperparâmetros. A margem estreita sobre a regressão logística já indicava que o
limite não estava no algoritmo, o que a curva de aprendizado confirmou depois.

Hiperparâmetros escolhidos: `learning_rate` 0,05, `max_depth` 10, `max_iter` 100,
`min_samples_leaf` 100 e `l2_regularization` 1,0.

### Um critério que foi revisado

Os limiares de aceitação estavam em [`config/settings.py`](config/settings.py) desde
o primeiro commit, antes de qualquer treino. Na primeira execução o gate de ganho de
acurácia reprovou, com 3,70 pontos contra os 5,00 exigidos, e interrompeu a pipeline.

A resposta foi enriquecer a base com os indicadores socioeconômicos que faltavam, o
que levou o ganho a 3,83 pontos. Ainda insuficiente.

A medição do teto explicou por quê. Substituindo o modelo pela taxa real do município
no próprio ano (o oráculo que a correção de vazamento removeu), a acurácia chega a
64,32%, um ganho de 4,55 pontos. **Nem o oráculo passaria.** O critério era
inatingível por construção, porque a variância restante está dentro do município e
nenhuma variável da base a alcança.

O gate passou a medir a captura do teto, com mínimo de 75%. A mudança está registrada
na configuração com os números que a sustentam, e foi feita depois de tentar melhorar
o modelo, não no lugar disso.

## 6. Métricas de avaliação

Relatório em [`reports/avaliacao.md`](reports/avaliacao.md).

| Métrica | Treino | Teste |
|---|---|---|
| ROC-AUC | 0,6738 | 0,6604 |
| Average precision | 0,7528 | 0,7366 |
| Acurácia | 0,6433 | 0,6361 |
| F1 | 0,7371 | 0,7332 |

Os três gates passam: ROC-AUC de 0,6604 contra o mínimo de 0,60, captura de 84,29%
do teto contra o mínimo de 75%, e diferença treino-teste de 0,0134 contra o máximo
de 0,10.

A escolha do limiar pesa mais que a acurácia. Em 0,5 o modelo encontra apenas
33,9% das crianças que não serão alfabetizadas, porque esse ponto maximiza acurácia e
trata falso positivo e falso negativo como equivalentes. Neste problema eles não são:

| Limiar | Encontra em risco | Precisão | Acurácia |
|---|---|---|---|
| 0,50 (padrão) | 33,9% | 0,582 | 0,636 |
| **0,65** | **74,2%** | 0,492 | 0,588 |
| 0,70 | 85,4% | 0,458 | 0,535 |

A recomendação é operar em 0,65 e tratar a saída como lista de prioridade, não como
diagnóstico.

## 7. Interpretação dos resultados

Relatório em [`reports/interpretabilidade.md`](reports/interpretabilidade.md).

Importância por permutação sobre as colunas originais e SHAP com as contribuições
somadas de volta às variáveis que as originaram:

| Variável | Queda no ROC-AUC | Direção do efeito |
|---|---|---|
| `taxa_municipio_ant` | 0,0368 | valores altos alfabetizam |
| `sigla_uf` | 0,0160 | categórica |
| `meta_municipio` | 0,0152 | valores altos alfabetizam |
| `ideb_municipio` | 0,0055 | valores altos alfabetizam |
| `taxa_uf_ant` | 0,0046 | valores altos alfabetizam |

A história do próprio município domina, com peso 2,3 vezes maior que a segunda
variável. As cinco mais influentes são territoriais, e o que descreve o aluno quase
não pesa: `rede` fica em décimo e `caderno` não entra no top dez, coerente com uma
atribuição aleatória de prova.

**Ressalva sobre causalidade.**
O modelo mede associação dentro do que enxerga, e o
que ele enxerga são doze variáveis de município ou UF e duas do aluno, `rede` e
`caderno`, ambas administrativas. Não há nenhuma sobre a criança em si, o
professor ou a família, então o território absorve tudo o que está correlacionado com
ele. Subir o IDEB não causa alfabetização: ambos são consequência da mesma qualidade
de ensino.

## 8. Insights encontrados

Relatório em [`reports/aplicacao.md`](reports/aplicacao.md).

**Desempenho por nível de agregação.** No grão individual o ROC-AUC é
0,66, mas agregando as predições por município a correlação com a taxa real é de
**0,827**, com erro médio de 7,47 pontos. Os erros individuais são grandes e não
sistemáticos, então se cancelam na média. O modelo não sabe qual criança não será
alfabetizada; sabe quantas não serão.

**Volume de dados.** A curva de aprendizado é plana entre 224 mil e 1,49
milhão de alunos, variando na terceira casa decimal. O limite é a granularidade da
informação, não o volume.

**Perfis de município.** O agrupamento separou os municípios em quatro
perfis. Dois deles têm exatamente o mesmo PIB per capita, R$ 16,6 mil, e taxas de
47,3% e 74,0%:

| Perfil | Municípios | Taxa | IDEB | PIB per capita |
|---|---|---|---|---|
| Pequeno de baixa renda, desempenho crítico | 1.590 | 47,3% | 4,85 | R$ 16,6 mil |
| Urbano de grande porte | 1.038 | 62,1% | 6,03 | R$ 49,3 mil |
| Pequeno e próspero | 1.538 | 70,4% | 6,50 | R$ 47,7 mil |
| Pequeno de baixa renda, bom desempenho | 1.351 | 74,0% | 6,08 | R$ 16,6 mil |

São 1.351 municípios de baixa renda alfabetizando acima da média nacional.

## 9. Limitações do projeto

**Teto de desempenho.** Com informação municipal, o ganho máximo de
acurácia sobre o baseline é de 4,55 pontos, medido substituindo o modelo por um
oráculo. O modelo entrega 3,83, ou 84% desse limite. Superar isso exigiria variáveis
de aluno, professor, turma ou família, que a base não tem.

**Identificadores anonimizados.** Aluno e escola são publicados como máscaras,
reatribuídos a cada edição, o que impede acompanhar trajetória individual ou construir
histórico por escola. Só o município é rastreável entre anos.

**Série temporal curta.** O município mediano teve 112
alunos avaliados, o que dá desvio amostral de cerca de 4,6 pontos na taxa. A variação
entre 2023 e 2024 tem desvio de 16,4 pontos, com 17,9% dos municípios oscilando mais
de dez pontos em um ano. Por isso não há classificação de trajetória por município: a
leitura de ritmo é agregada, onde o erro de amostragem se cancela.

**Escopo da população.** Os 513 mil alunos sem prova aplicada não
entram na modelagem, porque as variáveis que os identificam são as excluídas por
vazamento. O modelo prevê desempenho entre quem é avaliado; participação fica fora do escopo.

**Causalidade.** A ressalva da seção 7 vale para todos os resultados.

## 10. Aplicação prática para políticas públicas

A saída consumível é a tabela `risco_municipio`, publicada no BigQuery: uma linha por
município, com taxa prevista, perfil, marcação de amostra pequena e distância até a
meta de 2030.

**Priorizar onde atuar.** O quinto mais crítico reúne 1.028 municípios, dos quais 690
no Nordeste e 211 no Norte.

**Separar participação de aprendizagem.** Os dois se
comportam de forma oposta entre regiões. O Sul lidera em desempenho entre os testados
e cai para terceiro no indicador oficial por ter a maior ausência do país, 18,5%,
enquanto o Nordeste tem a maior participação com desempenho abaixo da média. Levar a
criança à avaliação e garantir que ela aprenda pedem políticas diferentes, e um
indicador único não diz qual está falhando.

**Comparar pares.** Os perfis permitem confrontar municípios de contexto semelhante.
A diferença de 27 pontos entre os dois grupos de mesma renda indica margem de melhoria
não explicada por recursos, e aponta onde investigar práticas de gestão.

**Acompanhar a meta.** No agregado o país avança 2,68 pontos por ano contra os 2,76
necessários, uma defasagem de menos de um décimo de ponto.

## 11. Possíveis evoluções futuras

**Uma terceira medição.** Com 2025, a trajetória de cada município passa a ser
separável do ruído amostral, o que habilita a classificação individual que este
projeto teve de descartar.

**Variáveis dentro do município.** O teto medido é do que a informação municipal
permite. Censo Escolar traz infraestrutura, formação docente e tamanho de turma;
Cadastro Único traz condição socioeconômica familiar. São as variáveis que explicariam
a variância que hoje sobra.

**Investigar os municípios que superam a própria renda.** Os 1.351 municípios de
baixa renda com bom desempenho são a pergunta de pesquisa mais promissora que este
trabalho levanta e não responde.

**Calibração e limiar por contexto.** O limiar de 0,65 é global. Municípios com
histórico e porte distintos podem justificar pontos de corte próprios, ajustando o
equilíbrio entre alcançar mais crianças e sinalizar menos falsos positivos.

**Monitoramento em produção.** A pipeline grava métricas a cada execução em
`reports/`, o que permitiria comparar rodadas e detectar deriva quando novos anos
forem incorporados.

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
│   ├── pipeline.py    # orquestração das nove etapas
│   ├── visualization/ # gráficos e material de apoio
│   └── export/        # publicação da camada Gold no BigQuery
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

**Executar a pipeline completa**

```bash
python -m src.pipeline
```

Nove etapas, da extração à publicação na Gold, com dependências declaradas. Etapas
cujos artefatos já existem são puladas; `--do-inicio` refaz tudo e `--somente-local`
pula o que depende do BigQuery.

Dois pontos interrompem a execução: a validação de qualidade, quando a aprovação
cai abaixo de 90%, e o treino, quando o modelo não alcança o desempenho declarado
em [`config/settings.py`](config/settings.py).

---

## Autor

**Thiago Corrêa Carvalho Diniz** — RM 371212

Pós-Graduação AI Scientist — FIAP
