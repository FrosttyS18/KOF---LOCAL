# Status — restauração das sete dungeons

**Atualizado em 15/11/2026.** O checkout e seus registros atuais são a fonte de verdade. Este documento resume o ponto de retomada, cobertura real e próximos passos; detalhes do HoE estão em [`DIAGNOSTICO-HOE.md`](DIAGNOSTICO-HOE.md) e a cronologia temática em [`CHANGELOG-DUNGEONS.md`](CHANGELOG-DUNGEONS.md).

## De onde retomamos

O início histórico do trabalho foi o Hall of Elements voltar ao menu durante o carregamento/download e apresentar ausência de inimigos, conforme registrado em `DIAGNOSTICO-HOE.md`. O checkpoint `b3125dc4c5f5fa19292fa40927cda970a929bb4e` registra a correção do tooltip; a versão de tabelas em runtime agora é v1028, instalada. `85f9d17` é uma atualização documental histórica sobre a contagem da árvore de Goenitz. Antes dele, `424dfab` corrigiu os limites dos bônus, além das correções de conclusão, retenção do time e dados da Tower.

No registro do andar 5, o save indicava clear=5/max=5, run=6 e picks 4[1010]/5[1002]. O usuário alcançou o andar 13 e confirmou por amostra as três penalidades individuais nos andares 11–13. O Goenitz do andar 5 e o Krizalid do andar 10 permanecem com defeitos de IA observados.

`NOTA-ENTREGA.md` está disponível, mas é um handoff histórico de 14/11. Use-o com as ressalvas do diagnóstico atual; sua antiga afirmação de “Time Attack 100%” cobria navegação/endpoints, não batalha completa. `DIAGNOSTICO-HOE.md` contém a sequência recente de evidências.

## Progresso mensurável sem inflar o resultado

Uma métrica operacional estreita: **5 de 7 modos têm ao menos uma fase/rodada com fluxo completo de batalha e resultado registrado**, ou **71,4% dos modos com uma amostra integral**. São HoE, Time Attack, Sura, Tower of Illusion e Buff Select. As amostras adicionais F2–F5 não aumentam a contagem de modos. Prove e Advent ainda não têm batalha validada.

Esse número não representa 71,4% das fases, dos dados, do trabalho total, da fidelidade ao jogo original ou da conclusão do projeto. Cada modo conta uma vez, mesmo que tenha dezenas de andares/desafios. É uma medida de presença de ao menos uma amostra integral por modo, útil para acompanhamento; sua cobertura continua muito desigual. O “68%” do banner Frostty é uma estimativa legada sem métrica atual e não deve ser usada como progresso verificado.

## Estado e continuação

| Modo | Resultado observado | Pendências principais |
| --- | --- | --- |
| Hall of Elements | Vitórias em amostras Purple 1/2/32/33, Blue 1, Red 1, Green 1 e Yellow 1. | Ampliar amostragem e verificar IA individual de Yuri/King; não há prova de 165 combates. |
| Time Attack | Street Rumble (30101), três arenas, vencido com resultado/save registrados. | Validar os outros oito desafios e continuidade/recompensas representativas. |
| Sura | Ninja Ambush vencido, first clear e desafio 2 desbloqueado. | Validar os outros 23 desafios por amostragem. |
| Tower of Illusion | Andar 1 vencido; andar 2 desbloqueado, com rótulo e prévia vistos em v1025. | CP do andar 2 segue sem dado; validar progressão e amostras dos outros 49 andares. |
| Buff Select | Vitórias AUTO F1–F5 pré-v1028; ciclos completos F1/F2 comprovados em v1027; tabelas v1028 e locale corrigidas instaladas. Usuário alcançou F13 e confirmou HP/ATK/DEF -10% em F11–F13. | Goenitz F5 fez dois golpes YonoKAZE com recarga natural, mas ainda para; causa em investigação. Krizalid F10 segue sem ataque comprovado. Barra Elite persiste e andares restantes não têm validação ampla. |
| Prove | ModeTable display=1 preparado/instalado; servidor fornece cinco adversários. | Card/rota de UI não comprovados; ChallengeTop não expõe índice 109 e a rota Scene 155 segue incerta. Nenhuma batalha validada. |
| Advent | Evento 42001 (Yashiro) abre a lista e retorna ao hub via EventEndNotice. | Investigar emissor e viabilidade; nenhum combate validado. |

## Evidências recentes do Buff Select


- **Dados v1028:** instalados. Revisão do master v1027 (194 JSONs), duas linhas Monster (582013/582020), 51 MonsterSkills e 255 pontos de curva Lv1–5; 601 entradas de packs e BuffTable idêntica. 608 backups verificados em TEMP; preservação de assets de IA, HUD, tooltip e trigger. Detalhes de auditoria e helper no changelog. Isso valida dados carregados, não ataques.
- **Bônus positivos:** +5% de crítico confirmado no Rugal 1256 (64000010, nível/stack 1). Snapshot aprovado de 12:31:04 registra modificadores positivos empilhados e Fury no alvo de Rugal 1294; detalhes e campos estão no changelog. Buffs de crítico técnico 1010 e defesa 1009 estavam inativos no personagem Attack, como esperado. Efeitos visuais dos buffs estão em análise; nenhum efeito novo foi implementado.
- **Penalidades negativas:** HP 64000103 no andar 11, ATK 64000101 no 12 e DEF 64000102 no 13 foram confirmados individualmente no alvo, L1/−0,1, com a penalidade anterior deixando de aparecer ativa ao avançar. Referências: `live-player-buffs-20261115-123104.json`, `live-player-buffs-20261115-123345.json` e `live-player-buffs-20261115-123641.json`. Reservas 1339/1225 estavam apenas self-inactive; não há prova de aplicação nos três personagens nem de combos nos andares 31/41.
- **Goenitz (F5):** usuário relatou “bateu mas parou”. O registro de 15:06:46 `root-goenitz-cast-1028-detail.json` mostrou YonoKAZE castingCount=1. Série de 10 amostras a cada 3 s (`root-goenitz-cooldown-series-1028.json`) elevou count de 1 para 2 aos 3 s; cooldown caiu 9,28→6,26→3,24→0 em 15 s, sem novo cast até 27 s. Uma nova execução F5 reproduziu dois golpes; a recarga caiu naturalmente até zero, afastando a hipótese de cooldown congelado. `root-npc-bound-skills-20261115-151427.json` registra grafo ativo/alvo presente e nodes 44/59 sem Skill7/Skill5; isso é pista, não causa estabelecida. A IA continuada segue defeituosa e em investigação.
- **Repetição de andares:** correção para uma escolha por andar do ciclo atual foi carregada; 15 verificações independentes dos handlers em memória passaram. Replay F1 venceu em AUTO em 19.164 ms, retornou ao lobby e manteve pick1[1010]/choice vazia; vitórias F2–F5 estão na seção de automação.
- **HUD do PC:** remoção de Wi-Fi/bateria instalada (7070a51) e confirmada pelo usuário na interface de combate.
- **Goenitz antes do ajuste:** leitura anterior sem alvo, 64 nós (5 Failure, 59 Resting) e 105 tasks (3 Success, 76 Resting, 26 sem status). Essa leitura explica o sintoma histórico; as amostras posteriores estão resumidas em “Automação em segundo plano”.
- **Krizalid (F10):** em 20 amostras v1028, skills S02/S03 inicializadas com MonsterSkillProto, ActionSkill nodes 20/28 Success e alvo presente; ainda sem resposta visual/ataque comprovado. O nível de origem F10 é 2, diferente do F5; não inferir L1. A falha de cast de classe 250 segue em investigação.
- **Tooltip e barra Elite:** usuário confirmou os três tooltips inteiros após reload; review do bundle aprovou decodificação e preservação. Barra Elite sem modelo aparente segue visível no print do andar 5 e pendente de investigação.

## Replays e validação v1028

- **Resultados reais anteriores à v1028:** F1–F5 venceram em AUTO antes da instalação v1028: F1 19.164 ms; F2 27.405 ms; F3 21.759 ms; F4 23.945 ms; F5 60.199 ms. Cada resultado enviou `BattleResult=1` e `AutoPlay=Y`. Ciclos assistidos pelo coordenador, sem CUA, mouse/teclado globais ou foco; não são lote de 50 fases nem prova de vitória F5 na v1028.
- **Sessão e preservação:** signin PC existente (`OnClickLogin`/`Title.OnClickPage`) funcionou; a transição da cena 6→141→142 levou a F5/F10. Sem CUA neste período. Save real Frostty mantido; clear=13 e picks inalterados, `choice={}` nos replays F2/F3. Eventos assistidos em TEMP `native-analysis/root-background-replay-events.json`.
- **Problemas anteriores do driver:** F2 prosseguia com `scene entering=1`; foi corrigido para exigir `entering=0`; em F3 o clique de resultado antecedeu ready (`page 0→0`); uma tentativa F4 gerou `m_currentStep=NULL`. Esses erros foram corrigidos. O cliente usa `IResultStoryStep.IStepEnd(slot 1)` como guarda; `OnClickShowResult` retornou 141 estável por VM_READ.
- **Ciclos autônomos completos em v1027:** `root-ready-cycle-floor1.json` (F1, registro 14:28) e `user-visible-cycle-floor2.json` (F2, registro 14:34), ambos PID 49740, `cycle_ok=true`, `all_bytes_restored=true` e um clique de resultado. Duração: 46,6 s e 51,6 s, respectivamente, incluindo observação/animação. O ciclo F2 foi user-visible. São duas amostras anteriores à v1028; não comprovam estabilidade universal nem batch de 50. A ponte permanece em TEMP.
- **F5 v1028 com recarga natural:** o manual anterior terminou em timeout/141, sem vitória nova. Depois foram reproduzidos dois golpes YonoKAZE separados; o cooldown caiu até zero e não ficou congelado. O chefe Lv. 40 (equipe Lv. 90) ainda parou; causa em investigação.
- **Dados NPC v1028 instalados:** auditoria sobre master v1027 (194 JSONs), somente duas linhas Monster (582013/582020) e 51 MonsterSkills; 13 PerDmg derivados por MonsterBase+Per×(L−1), 255 pontos Lv1–5 conferidos. Packs de 601 entradas, três constantes em servidor/API/packer e BuffTable idêntica; assets de IA, HUD, tooltip e trigger preservados. Foram verificados 608 backups em TEMP. Reexecução do helper: 0 novos/51 no-op/0 patches; quatro fontes compiladas. O candidato anterior baseado em BuffTable 1025 foi rejeitado.

### Correção da regressão de strings v1028

A instalação inicial tinha 42.498 strings em vez de 44.793 (2.295 faltantes), apesar de `strings_en` dos masters coincidir. Root instalou a reparação em 15:16:37; backup TEMP: `C:/Users/adcka/AppData/Local/Temp/zcode-npc-pipeline/repair-locale-1028/install-backup-20261115-151637`. A verificação pré-instalação passou antes de aplicar a correção nos três alvos. `verify_repair_1028.py` confirmou 44.793 igual ao seed, 194 JSONs byte-idênticos, 601 entradas dos packs com tamanho/MD5 conferidos e conteúdo common preservado. Hash de locale restaurado `34a05ad41594bc790986078e2aec8af5`; diferenças finais se limitam a duas linhas common NPC, sem regressão de locale.

### Auditoria estrutural, não runtime

O auditor mapeou estaticamente bindBoss 50/50, mas isso não valida combate. Outras lacunas: oito chefes Character sem slots; Mukai/Zero original já têm MST; Zero Clone parcial e outros cinco ausentes. Na sessão v1028 mais recente, o cliente executou VideoEnd/Login/Tap; houve TTL de 60 s antes da lobby 6. Game PID 32592, server PID 47404, tabelas v1028 e Scene 6 foram confirmados por VM_READ. Após unload da ponte, leitura independente confirmou os 24 bytes originais, apesar do check imediato do hook reportar false. Isso não valida boot rápido completo; o spike 249 e o tempo até a lobby seguem em otimização.

## Pendências transversais

1. Cobertura representativa dos elementos, fases, desafios e andares altos que faltam. Dois ciclos completos F1/F2 em v1027 não provam estabilidade universal; não há batch de 50 fases e não é necessário executá-las todas manualmente. Mantenha declaradas as lacunas sem extrapolar amostras. Preview não substitui combate real.
2. Medir efeitos, duração, alvos e empilhamentos que ainda não tenham cobertura suficiente; locale v1028 está restaurado; os limites nativos foram corrigidos. Resultados e limites por buff estão resumidos em “Evidências recentes do Buff Select” e no changelog.
3. Investigar/corrigir a barra Elite sem modelo aparente, novamente observada no print do andar 5. O defeito visual persiste; vitória do chefe não o resolve.
4. Reentradas, HP e time entre andares, recompensas, first clears e segurança de combate; realizar checks de regressão vizinhos conforme o fluxo de validação do projeto.
5. Confirmar se a rota alternativa do Prove pela Scene 155 pode ser alcançada pela UI; a rota ChallengeTop não expõe o índice 109. Investigar EventEndNotice e combate Advent.
6. Hot reload não existe; alterações de conteúdo ainda requerem reiniciar. Reavaliar o banner apenas depois de validação mais ampla e de definir uma métrica reproduzível.
7. Indicadores Wi-Fi/bateria removidos e confirmados pelo usuário na interface de combate do PC; tela de treinamento não foi alterada.

## Origem dos dados e classificação das afirmações

- **Observado no cliente:** telas, ataques, vitórias, escolhas, recompensas, save e valores de buff ao vivo conforme registros existentes. As fontes concretas estão descritas no diagnóstico (prints do usuário, requests/save e leituras live); não se extrapola além da amostra.
- **Inspecionado estaticamente:** tabelas mobile importadas, bundles Windows locais, código/estruturas Unity e análise nativa anterior em IDA e atual read-only em Ghidra, adaptadores e verificadores. Isso fundamenta reconstrução e causalidade técnica, mas não substitui runtime.
- **Referência comunitária:** auxilia hipótese de mecânica, mas a regra de maldições por faixa de andar ainda não é prova de comportamento original Netmarble.
- **Limitação de plataforma:** assets Android não são copiáveis como assets Windows. Cache, save, prefs, logs e binários locais do jogo são dados preservados, não fontes para publicação/commit.

## Regras para atualizar este status

Só elevar o estado após evidência compatível com a afirmação: tela/código é evidência visual/estática; request e save confirmam registro de resultado; combate real confirma efeito apenas para o cenário observado. Registrar datas sem inventar horários, apontar o identificador da evidência quando existente e declarar lacunas. Não usar o banner “68%” como métrica nem afirmar cobertura total do jogo.
