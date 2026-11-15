# Diagnóstico e validação: Hall of Elements (2026-11-14)

## Estado atual: v1016 em teste
- A v1014 carrega a arena Purple sem inimigos; a v1015 importa os chefes, mas também fica sem inimigos porque faltavam os monstros das ondas anteriores.
- O grafo original Purple prepara Pierrena e Ryo antes de liberar Flame Walker. Os 15 nomes `Monster.*.HighComedown` da referência foram confirmados dentro do pacote original PC de gatilhos, e todos os seus pacotes de modelos estão presentes no cache.
- Fechamento acumulado: 15 MonsterTable, 57 MonsterSkillTable, 6 MonsterGrowthTable (growthType 100), 151 MonsterLevelStatTable (levelStatType 100), 55 AiGroupTable (700/701/702/705/706) e 15 nomes traduzidos. SkillTable permanece intocada.
- Importações em cópias descartáveis verificadas: todas as linhas preexistentes permanecem iguais; uma segunda execução não muda os arquivos. O teste v1016 acrescenta apenas os dez perfis, 37 habilidades, 44 registros de IA e dez nomes que faltavam após v1015.
- Rebuild v1016 concluído e jogo reaberto. Presença/ação das ondas e chefes, vitória, recompensas e retorno à lista continuam pendentes de validação real.
- O mantenedor autorizou fechar/reabrir o jogo conforme necessário, sem pedir confirmação a cada reinício. Os comandos de mouse e teclado continuam proibidos.
- Checkpoint v1014 enviado para main: `3e61394`. Nenhuma funcionalidade além da evidência acima foi declarada concluída.

## Sintoma (evidência real)
- Card "Hall of Elements - Purple" visível no hub; clique humano não abre nada e não gera endpoint nem erro nos logs (gate do próprio cliente).

## Achado (IDA — análise do Codex)
- Fontes: `%TEMP%\codex-kofas-zcode-bridge-review\native-analysis\gates.txt` e `decomp_hoe_nomes.txt`.
- `sub_1800083F0` é `List.Contains` (`Count != 0` e `IndexOf != -1`).
- `decomp_hoe_nomes.txt:186-193`: `IsWhiteListUser == false` **e** `Contains(whitelist, eventIndex) == true` → `IsOpenDungeon` retorna `false`.
- Conclusão: a `WhitelistStageEntranceTable` que criamos **restringia** esses 15 índices de evento a testers — não os liberava. O cliente bloqueia a entrada localmente, por isso o clique não gerava requisição.

## Mudança aplicada (aguardando regeneração dos tablepacks)
- `game/_preservation/server/tables/data/WhitelistStageEntranceTable.json`: `rows = []` (arquivo mantido, `_comment` atualizado).
- `game/_preservation/server/kofserver.py`: `TABLE_PACK_VERSION` 1009 → 1010.
- `game/_preservation/tools/make_tablepacks.py`: `VERSION` 1009 → 1010 (ambos devem permanecer iguais).
- Schedules duplos de Transcendência no `gameapi.py` preservados intocados (isolamento de variável).

## Pendências
- Regenerar os tablepacks com o jogo fechado e reiniciar servidor/jogo (fluxo do Codex).
- Validação visual em runtime PENDENTE: card HoE deve abrir o evento ao clicar. Não declarar corrigido em runtime antes dessa validação.

## Resultado v1010 (validação parcial do Codex)
- Gate whitelist liberado: o card responde ao clique e inicia a transição (`player-codex-v1010.log`: `OnCheckSpecialOpen → GoSPQuestOpen.b__0 → ChangeCurrentScene`, Scene 71), porém **retorna à tela raiz DUNGEON sem nenhuma chamada questEventList/questEventOpen**. HoE NÃO está corrigido; hipótese (cache do QuestEventManager vazio / grupo 41000 não resolvido) segue em investigação IDA do Codex.

## Refs de stage pendentes (checker do Codex)
- Stages dos 7 modos novos + ChallengeStageTable referenciam 26 ResourceMapTable e 298 StageBalanceTable ausentes; todos existem na fonte mobile (`mobile-ref-running/kofas_server/server/tabel`). Time Attack: maps 9211, 9215, 9801..9806; balances 3010101..3010109.
- `import_dungeons.py` agora fecha esse ciclo (falha explícita se faltar na fonte; sem inventar valores). Append real nos JSONs + rebuild dos packs v1011: execução pendente do Codex.
- Validação futura: rodar o importador, rebuild, reiniciar servidor/jogo; revalidar Time Attack (eventStart → batalha sem travar) e o fluxo HoE.

## Resultado v1011 (leituras nativas do Codex)
- 26 maps + 298 balances appended corretamente; o erro NavMesh DESAPARECEU, mas o carregamento segue preso.
- Leitura nativa: após clique HoE, currentScene = 71 (`Scene_Single_SPQuest_Mode`), entering = 0, preso em NOW LOADING; Esc volta ao 131. Time Attack: Scene 77 carrega sem erro NavMesh, loading pendente.
- Causa nova: `Scene_Single_ChallengeMode.Initialize` (RVA 0x1518D90) chama `DifficultyTable.GetDifficultyRange(202)` — a DifficultyTable do PC não tem NENHUMA linha modeIndex 202 (mobile: difficultyIndex 26). Os novos QuestEventStages referenciam 40 difficultyType ausentes [11..16, 21, 2101..2133]. Total 41 linhas, todas na fonte mobile. `QuestEventStageInfo` (ctor 0xCBE130) consulta o diff proto antes da lista HTTP.
- `import_dungeons.py` estendeu o fechamento para DifficultyTable (+ difficultyIndex do mode 202) e importa strings reais de `difficultyNameStringTag` E `difficultyNameStringTagEng` via `strings_add` (sem sobrescrever existentes, sem inventar labels). Versões 1012.
- Pendente: Codex executar o importador em cópia e integrar SOMENTE `DifficultyTable.json` + `strings_en.json`; rebuild v1012; teste visual (HoE e Time Attack).

## Estado v1012 em runtime + causa do modal (2026-11-14)
- HoE Purple ABRE a lista de fases e a seleção de equipe/strikers; `questEventStart` 4100101 retorna ResultCode 0; mesmo assim surge o modal DATA DOWNLOAD HAS FAILED. **Nenhum GET CDN após o Start** e o mobile dá a MESMA falha — a causa é interna do cliente (a confirmar com observe_assets na reprodução única: m_downloadingErrors/m_unresolvedDownloadList).
- ResourceMap: o schema PC NÃO tem campo `resourceMapBundle`; o cliente resolve o bundle a partir de `resourceMapScene` internamente — não se alega ausência de asset por nome.
- Barra 3/3: prefab `uiunit_combineplaycount` (cache MD5 6020209cd009a2bee0e9dd75cb222a15) e `v_spquestmode` carregam `System.QuestEventEntryCount.Info_01.Name` e `Info_02.Name`. Info_01 é lacuna REAL (ausente no mobile SystemTable/pt/cadangan); Info_02="Entries" e os `Difficulty.Eng.*` entram na v1013 (importer ajustado), aguardando runtime. Versão já está 1013; sem bump adicional.

## Raiz do modal CONFIRMADA (v1014)
- Falha live (PID 2788, coro preso do LoadManager): pedia asset `comedown_flame_walker_violet` do bundle `prefabs_eventsystem_trigger_comedown_highcomedown`. Leitura UnityFS do bundle PC original (md5 6af2d750a50492afb4a048f65fb10639): contém `comedown_flame_walker_purple.prefab` (+blue/green/red/yellow), **ZERO violet** — typo de origem nas tabelas mobile (por isso o mobile falha igual).
- Correção: 33 rows do evento 41001 (`4100101..4100133`), campo `singleTriggerName` violet→purple — editadas no JSON e cobertas por `adapt_triggers_to_pc()` no importador (rerun repara; única exceção append-only, documentada na docstring). Versões 1014.
- Codex: assert diff = 33 campos, rebuild v1014 e teste runtime (batalha HoE Purple deve carregar).

### Resultado v1014 em runtime (2026-11-14)
- Rebuild 1014 concluído; diff contra HEAD = somente os 33 campos `singleTriggerName` (confirmado pelo Codex).
- Teste do importador em cópia descartável: removidas as 33 stages Purple → o import repõe as 33 já com `..._purple`; rerun idempotente (0 renomes).
- Runtime: o COMBATE ABRIU — screenshot Codex da arena Purple com HUD de controle 02:41, currentScene 60, entering 0. Fim de batalha/win e recompensas PENDENTES (usuário foi pedir para concluir a batalha).

## Estado v1015 em runtime: arena sem inimigos (2026-11-14)
- 5 chefes + deps (MonsterSkill/Growth/LevelStat/AiGroup, 193 rows) importados; cliente atualizou os packs sem exceções no log; os 5 chefes carregam NA RUNTIME com 423 protos de nome exato — stale-cache DESCARTADO.
- Arena abre (Scene 60, timer roda), ZERO inimigos. `player-codex-v1015.log` sem nenhum erro/exception de Monster/trigger (só 2 avisos de vídeo) — o spawn falha silenciosamente.
- CAUSA PROVADA pelo dump do GraphOwner em runtime (`native-analysis/hoe-live-graph.json`): StageMonsterList=6, preparedTypes=1, active=0. O grafo NODE 7 cria `Pierrena.Normal.HighComedown` e `Ryo.Elite.HighComedown` em 2 ondas ANTES do NODE 9 (boss Flame Walker). O PC NÃO tem esses 2 monstros (fonte: 530003/530005) — o import só de chefes ficou incompleto; NÃO é preciso patch nativo.
- Correção (aguardando execução do Codex em cópia): `import_hoe_monsters` agora seleciona TODOS os 15 rows fonte `Monster.*.HighComedown` (5 chefes + 10 mobs/elites das ondas), mesmo fechamento skill/growth/levelstat/aigroup; todos os 57 skillNIndex resolvem em MonsterSkillTable (SkillTable intocada). Versões 1016.
- Previsto: MonsterTable +10 (530003/5/8/9/10/12/13/15/17/18), MonsterSkillTable +37, AiGroupTable +44 (700/701/702/706), Growth/LevelStat +0. Validação runtime (ondas + boss + fim de batalha) PENDENTE.

## Validação real concluída na v1016
- O mantenedor confirmou ondas, chefe derrotado e recompensas na primeira fase Purple. Prints mostram RESULT com ouro 3600, duas cápsulas e dez moedas; retorno com STAGE 1 COMPLETED e Entries visível.
- Requisição real questEventEnd: stage 4100101, BattleResult 1, ClearTime 12, PlayTime 12764; resposta HTTP 200/ResultCode 0. Save persistiu clears 1 e três missões concluídas.
- O último nível 4100133 ainda trava: a tabela de IA dos lutadores (grupo 301) não contém o grau 6 solicitado. Esse ajuste e a validação dos demais stages/modos ficam pendentes neste checkpoint.
