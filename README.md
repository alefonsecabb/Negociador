# Negociador — apoio a swing trade em ações da B3

Repositório: https://github.com/alefonsecabb/Negociador · Dashboard (após publicar no
GitHub Pages — ver seção correspondente abaixo): `https://alefonsecabb.github.io/Negociador/`

Ferramenta para **mapear preços de compra e venda** de uma estratégia de swing
trade em ações do Ibovespa e **gerar alertas** (com preço-limite já ajustado
para compensar o atraso do dado gratuito) para você executar manualmente no
seu homebroker. Inclui um motor de **backtest e validação walk-forward** para
testar, com uma carteira fictícia de R$100.000, se algum conjunto de
parâmetros sustenta a meta de **5% de rentabilidade por ciclo de 30 dias**
antes de arriscar capital real.

> ⚠️ **Leia antes de operar com dinheiro real.** 5%/mês equivale a mais de
> 80%/ano composto — muito acima do que a maioria das estratégias
> sistemáticas sustenta de forma consistente, líquida de custos e impostos,
> fora da amostra de otimização. O papel desta ferramenta não é prometer
> 5%/mês, é **medir honestamente** se algum modelo sustenta isso. Os
> relatórios de backtest e walk-forward (seção "Performance do backtest" do
> dashboard) mostram os números reais — inclusive quando eles não batem a
> meta — para você decidir com dados, não com expectativa.

## Como funciona

1. **Dados**: histórico e cotação via [yfinance](https://github.com/ranaroussi/yfinance)
   (gratuito, tickers B3 com sufixo `.SA`). Universo: ações do Ibovespa
   (`config/ibov_universe.json`, ~78 tickers, atualizado manualmente a cada
   rebalanceamento trimestral do índice).
2. **Estratégia**: swing trade *long-only*, com stop-loss/take-profit
   calculados por ATR e dimensionamento de posição por risco (ver
   `config/strategy_params.yaml`, todos os parâmetros documentados ali).
3. **Backtest + validação**: `backtest/engine.py` simula as operações sem
   lookahead, com custos reais da B3 (emolumentos + IR de swing trade).
   `backtest/walk_forward.py` calibra os parâmetros só em dados de TREINO e
   avalia em janelas de TESTE fora da amostra, mais um holdout final nunca
   tocado na calibração — a métrica-chave é **"% de ciclos de 30 dias que
   bateram a meta"**, sempre reportada ao lado do que não bateu.
4. **Monitor ao vivo**: roda no GitHub Actions (não precisa do seu computador
   ligado), varre o watchlist e as posições abertas, e grava alertas com o
   **preço-limite de compra/venda** já com uma margem de execução (compensa o
   atraso do dado) — ver "Preço-limite com margem" abaixo. Um alerta não
   confirmado nem ignorado **expira sozinho** após alguns dias
   (`config/strategy_params.yaml` → `alerts.expires_after_days`, padrão 2) —
   evita ficar com um preço-limite obsoleto pendurado e libera o ticker para
   um sinal novo. Você também pode **ignorar** um alerta manualmente (botão
   no dashboard, ou `confirm_execution.py --alert-id N --ignore`) se decidir
   não seguir a sugestão.
5. **Dashboard**: publicado no GitHub Pages, mostra carteira, posições,
   alertas do dia e a performance do backtest/walk-forward.
6. **Você decide e executa manualmente no homebroker.** A ferramenta nunca
   envia ordens sozinha. Ao confirmar que executou (pelo dashboard ou pela
   CLI), a carteira fictícia é atualizada para refletir o que você realmente
   fez.

## Preço-limite com margem de execução

O yfinance tem atraso típico de dado gratuito (minutos). Por isso, todo
alerta sugere um **preço-limite** diferente do preço de referência:

- **Compra**: preço-limite = referência × (1 + margem) — acima do preço
  visto, para não perder a entrada se o mercado já tiver subido um pouco.
- **Stop-loss**: preço-limite = stop × (1 − margem maior) — abaixo do stop,
  para garantir a execução mesmo com o preço já tendo caído mais.
- **Take-profit**: preço-limite = alvo × (1 − margem menor) — perder o alvo
  por 1 tick é aceitável; não vender no stop não é.

**Recomendação mais importante**: assim que uma compra for confirmada,
cadastre no seu homebroker uma **ordem stop de venda** (a maioria das
corretoras B3 oferece isso) nos preços de stop/take calculados pelo modelo.
Isso elimina completamente a dependência do atraso do nosso dado para a parte
mais crítica — a corretora executa em tempo real. O monitor ao vivo continua
checando esses níveis como alerta de reforço/backup.

## Resultado da validação (walk-forward, 30/08/2026) — a resposta honesta

Isto é o que realmente importa para decidir se vale operar com dinheiro real.
`run_walk_forward.py` calibrou `atr_stop_multiple`, `reward_risk_ratio` e
`risk_per_trade_pct` (grid search) usando só dados de TREINO, testou em 5
janelas de 6 meses **fora da amostra**, e reservou um holdout final de 18
meses nunca tocado na calibração:

| Métrica | Média das 5 janelas OOS | Holdout final (2025-02 a 2026-08) |
|---|---|---|
| % de ciclos de 30d que bateram a meta de 5% | **16,0%** | 25,4% |
| Retorno médio por ciclo | 0,54% | 1,56% |
| Drawdown máximo | — | -14,4% |

Os parâmetros vencedores (`atr_stop_multiple=3.0`, `reward_risk_ratio=2.5`,
`risk_per_trade_pct=2%`) já estão aplicados em `config/strategy_params.yaml`
e passam a ser os usados pelo monitor ao vivo. O detalhe completo, janela a
janela (uma delas teve retorno médio NEGATIVO de -1,25%/ciclo e 0% de acerto
da meta — o modelo não generaliza igualmente bem em todo período), está em
`reports/walk_forward_report.json`.

**Conclusão honesta**: mesmo calibrado, o modelo **não sustenta 5%/mês de
forma consistente** — na melhor janela (holdout) chega a 25% dos ciclos, na
média das janelas fica em 16%. Rodando os mesmos parâmetros calibrados sobre
todo o histórico 2019-2026 (não é out-of-sample puro, mas dá o quadro geral):
retorno médio de 1,13%/ciclo, 22,7% dos ciclos bateram a meta, drawdown
máximo de -20,7%, taxa de acerto de 46,8% em 1.124 trades. Isso é
consideravelmente melhor que os parâmetros default (0,83%/ciclo, 16,5%,
-23,5%), mas ainda muito abaixo da meta declarada. Use esses números — não a
meta original — para decidir se e quanto capital real faz sentido arriscar,
e considere revisitar a estratégia (outra variante, outro conjunto de
regras) se a meta de 5%/mês for inegociável para você.

## Rodando localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 1) baixa/atualiza o cache historico (8 anos, ~77 tickers do Ibovespa)
python -m negociador.cli.update_cache

# 2) roda o backtest completo e grava reports/backtest_report.json
python -m negociador.cli.run_backtest --start 2019-01-01

# 3) validacao anti-overfitting (walk-forward + holdout) - demora (~15-30min);
#    ao final, atualiza config/strategy_params.yaml com os parametros calibrados
python -m negociador.cli.run_walk_forward

# 4) roda o monitor ao vivo uma vez (gera alertas do dia)
python -m negociador.cli.run_monitor

# 5) gera os JSONs do dashboard e abra site/index.html no navegador
python -m negociador.cli.publish_site
python -m http.server --directory site 8000   # depois abra http://localhost:8000

# confirma que executou uma ordem sugerida por um alerta (ticker abre/fecha na carteira)
python -m negociador.cli.confirm_execution --alert-id 3
```

Testes: `pytest`.

## Publicando no GitHub Pages (ao vivo, sem servidor)

1. Nas configurações do repositório (`Settings → Pages`), defina **Source:
   GitHub Actions** (o workflow `.github/workflows/pages.yml` cuida do
   deploy do conteúdo de `site/`).
2. Garanta que Actions têm permissão de escrita: `Settings → Actions →
   General → Workflow permissions → Read and write permissions`.
3. Rode manualmente (aba **Actions** → escolha o workflow → **Run workflow**)
   `daily_cache.yml` uma vez para popular `data/cache/`, depois
   `monitor.yml` para gerar o primeiro estado/alertas. Os workflows
   agendados (`monitor.yml` a cada ~15min em horário de pregão, `daily_cache.yml`
   1x/dia) assumem daí em diante.
4. **Confirmar execução pelo navegador é opcional.** Por padrão, confirme
   localmente com `confirm_execution.py` + `git push`. Se quiser confirmar
   também fora de casa, cole na seção correspondente do dashboard um GitHub
   *fine-grained personal access token* com acesso restrito a este
   repositório e permissão só de `Contents: Read and write` — ele fica
   salvo apenas no `localStorage` do seu navegador.

## Estrutura do projeto

```
config/                    parâmetros da estratégia e universo de tickers
data/cache/prices/         histórico OHLCV em parquet (versionado no repo)
data/negociador.db         carteira fictícia, posições, trades, alertas (sqlite, versionado)
src/negociador/
  data_ingestion/           cliente yfinance + cache incremental
  indicators/                SMA/EMA/RSI/MACD/Bollinger/ATR/Donchian (pandas/numpy puro)
  strategy/                  regras de entrada/saída, position sizing, preço-limite
  backtest/                  motor de simulação, custos/IR, métricas, walk-forward, calibração
  portfolio/                 carteira fictícia (sqlite)
  live/                      monitor ao vivo, alertas, publicação dos JSONs do site
  cli/                       comandos (update_cache, run_backtest, run_walk_forward,
                              run_monitor, confirm_execution, publish_site)
site/                       dashboard estático (GitHub Pages)
.github/workflows/          monitor, atualização diária de cache, reconciliação, deploy do Pages
reports/                    saída dos backtests (json)
tests/                      pytest
```

Ver `config/strategy_params.yaml` para todos os parâmetros (com comentários
explicando cada um) e o histórico de decisões de arquitetura no plano original
do projeto.
