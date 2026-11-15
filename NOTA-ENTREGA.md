# NOTA DE ENTREGA — estado do projeto (2026-11-14, ~22h)

> Atualização do Codex: a nota abaixo é histórica. Consulte `DIAGNOSTICO-HOE.md` para a investigação e validação atuais.
> Checkpoints enviados para `main`: `3e61394` (entrada/arena) e `4eebcc1` (ondas, chefe, vitória, recompensas e progresso persistido da primeira fase Purple, v1016).
> Atualização v1017: fases Purple 32 e 33 validadas pelo Codex com ondas/chefe, vitória, recompensas e save. Foram acrescentados quatro registros de IA dos lutadores como adaptação de compatibilidade (originais não recuperados), preservando todos os dados anteriores. Demais elementos/stages/modos continuam pendentes; detalhes no diagnóstico.
> A interpretação antiga da whitelist estava invertida: a lista restringia os eventos para usuários comuns. A tabela reconstruída foi esvaziada após leitura do cliente.
> A afirmação antiga de “Time Attack 100%” comprova apenas navegação e endpoints; batalha completa e recompensas não foram validadas.

Handoff para continuação (Codex ou outra sessão). Meta original: as 7 dungeons que faltavam
funcionando na versão PC. Repositório: FrosttyS18/KOF---LOCAL (main). Últimos commits:
`2cc518c` (as 7 dungeons: dados+handlers), `4934e44` (HoE: whitelist/EventPage/marcadores, commit do
mantenedor), `98e708f` (schedules duplos).

## O que está PRONTO e VERIFICADO

- **Time Attack (Challenge)**: 100% no cliente PC — hub CHALLENGE com card nomeado, tela com os 9
  desafios reais (Street Rumble, Stadium of Kings, Sins Unleashed...), `challenge/eventInfo` e
  `challenge/rankingList` respondendo (provado no requests log). Handler: `ext_timeattack.py`.
- **Servidor**: 191 handlers (27 novos). Módulos: `ext_phantom`, `ext_sura`, `ext_prove`,
  `ext_timeattack`, `ext_buffselect` — portados do servidor da comunidade indonésia (v83/v158),
  referência completa em `C:\Users\adcka\Downloads\KOFAS-Offline\mobile-ref-running\kofas_server\`
  (extraído do APK; código-fonte + tabelas reais em JSON + ep_map com 362 endpoints).
- **Tabelas** v1009 (TABLE_PACK_VERSION em `kofserver.py` = `VERSION` em `tools/make_tablepacks.py`;
  SEMPRE iguais): QuestEventTable 59 linhas (HoE 41001-05, Advent 42001-06, Torre da Ilusão 107,
  BuffSelect 8101, Sura 10801, Prove 10901), 868 stages, tabelas dedicadas (Challenge*, Sura*,
  Prove*, BuffSelect*, EventPage*), ModeTable 21 (botões de menu), WhitelistStageEntranceTable
  (CRIADA por nós — ver abaixo), memórias 3000000+ (596 itens), strings 42k.
- **Sem limites diários** (pedido do mantenedor): zero `limitPlayType` nos stages; HoE sem 3/dia;
  Auto-Clear de Sura/Torre de Ilusão sem gate diário.

## O problema do Hall of Elements — cadeia completa (RE do GameAssembly.dll)

Entrada do card: `EventQuestShortcut.EventQuestScheduledShortcut` → `IsOpenDungeon(0x1814FAD10)` →
`OnCheckSpecialOpen` → `GoSPQuestOpen` → `QuestEventManager.OpenCheckEventQuestStageCondition`.
Fatores descobertos (todos aplicados):

1. **WhitelistStageEntranceTable** (tabela que nem a comunidade mobile tinha): para não-whitelist
   users, `IsOpenDungeon` exige o questEventIndex em `WhitelistEntranceValueList(QuestEventIndex=3)`.
   Criamos com os 15 eventos → efeito imediato: os 5 elementos do HoE apareceram no hub.
2. **EventPageTable** (11 páginas, Flame Walkers/spines) — sem ela o clique entrava em NOW LOADING
   infinito. Importada (a nota da própria comunidade, v164, chama isso de "layar hitam").
3. **`specialQuestEventGroupOnOff=1`** nas 11 linhas de Transcendência: sem isso o clique rebotava
   ao menu raiz (o caminho comum só aceita questEventType 3).
4. **Schedules duplos no `player/poll`** (último commit): o hub lista banners por Category 2/Sub 3;
   `IsOpenDungeon` exige um schedule Category 3 com o índice do evento. Cada evento manda ambos.

**ESTADO REAL**: com (1) os cards apareceram; com (2)+(3) o clique passou a transicionar; (4) não
foi validado em tela ainda (o card sumiu do hub nas tentativas só-Cat-3; o commit duplo é a
hipótese final não testada). VALIDAÇÃO PENDENTE: card Purple visível + clique abre a tela do HoE
(assinatura no log: `questEventOpen`/`questEventList` com índices 41001+; Soul Quest dispara
endpoints `fighterquest/*`; Plugin Plant dispara `equipmentDungeon/*`).

## Ferramentas prontas

- `C:\Users\adcka\Tools\il2cpp\out_pc\`: script.json (221k métodos, RVA+nome; ImageBase real
  0x180000000), dump.cs (classes/campos/enums), decomp_hoe*.txt (pseudocódigo nomeado da cadeia).
- IDA 9.5 (hoe.i64/hoe2.i64) e Ghidra 12.2 (`decomp_hoe_ghidra.txt`) — ambos funcionam headless;
  idat às vezes dá error 4 reabrindo .i64 salvo → contorno: análise nova com `-o`.
- LDPlayer (emulator-5554, root ok) com o jogo mobile completo (servidor embutido v83) — oráculo.
- Cliente PC roda via exe direto (o play.cmd às vezes não lança o jogo; `__COMPAT_LAYER=RunAsInvoker`
  + args `-screen-fullscreen 0 -screen-width 1280 -screen-height 720 -logFile ...`).

## Armadilhas conhecidas

- Restart rápido do jogo deixa estado contaminado (overlay de loading preso sobre o lobby) —
  matar o processo e subir limpo resolve.
- Screenshots analisados por subagente têm erro de posição — NUNCA clicar por coordenada estimada;
  validar toda troca de tela pela assinatura de endpoint no `server/logs/requests-*.log`.
- A conta do save tem 75 lutadores awakened (requisito real do HoE atendido).
- Save intacto; só adições. Estado atual: servidor + cliente rodando com v1009 + schedules duplos.

## Próximos passos sugeridos

1. Validar (4): hub mostra os cards E o clique no Purple abre (`questEventOpen` no log). Se o card
   sumir de novo, o filtro do hub não é Cat — ler `UIPage/Scene_Single_SPQuest_ModeSelect` no dump.cs.
2. Batalha de validação end-to-end: `questEventStart` → fim → `questEventEnd` com recompensas
   (grupos 952001xx/9610001 + swap de marcadores 3999991-95 → memória do elemento).
3. Repetir entrada+batalha para Advent (42001), Sura (`suraDungeon/*`), Prove (`proveDungeon/*`),
   BuffSelect (`questEvent/buffDungeon*`), Torre de Ilusão (`questEvent/phantomTower*`).
4. Fidelidade fina depois: loja de memórias do HoE (moveShopSubType 704), regras JP opcionais.
