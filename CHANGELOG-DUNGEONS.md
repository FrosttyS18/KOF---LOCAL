# Changelog — restauração das dungeons

**Escopo:** histórico temático do trabalho de restauração das sete dungeons. Este arquivo resume commits já presentes em `main` e validações registradas; não substitui o diagnóstico detalhado do Hall of Elements em [`DIAGNOSTICO-HOE.md`](DIAGNOSTICO-HOE.md).

## Fontes e limites da evidência

A fonte de verdade para o estado é o checkout atual, seus commits e os registros técnicos/documentais existentes. As adaptações de dados partiram principalmente das tabelas mobile importadas e dos bundles do cliente Windows disponíveis localmente. Contratos e comportamentos foram confrontados, conforme cada item, com estruturas Unity e código nativo analisados anteriormente em IDA e atualmente por leitura estática no Ghidra, além de logs/requisições reais do cliente e dados de save registrados durante testes. Referências comunitárias pontuais são citadas no diagnóstico; uma regra atribuída à comunidade não equivale a comprovação do comportamento original da Netmarble.

Cliente Android não é fonte de assets intercambiáveis com Windows: seus assets não podem ser copiados como se fossem compatíveis. Cache, saves, prefs e binários de jogo não são parte dos commits de conteúdo. As evidências de testes são as descritas nos registros existentes; este changelog não afirma ter repetido testes.

## Linha do tempo por checkpoints

O início histórico da restauração foi motivado pelo Hall of Elements voltar ao menu durante o carregamento/download e apresentar ausência de inimigos, conforme o diagnóstico. Isso é diferente do checkpoint mais recente descrito no status. A `NOTA-ENTREGA.md` existe, mas é um handoff histórico de 14/11: suas afirmações devem ser lidas com as ressalvas registradas no diagnóstico e neste status. Em particular, a antiga frase “Time Attack 100%” referia-se à navegação/endpoints, não a batalha completa.

- **14 nov — HoE e dependências iniciais:** commits `3e61394`, `4eebcc1`, `7ad4fff`, `99437d7`, `b4a1bbc` e `401962e` restauraram carregamento e dados de inimigos, dependências de arena, fighters de grau alto sem alterar atributos dos inimigos, agrupamento dos elementos, missões/recompensas e identidade do banner. `DIAGNOSTICO-HOE.md` registra as causas nativas, alterações e cobertura real por versão.
- **15 nov — preparação de modos e dados PC:** `1ac6d0f`, `3549cad`, `b00bdf3`, `eb34219`, `863d3cc`, `053c7bf` e `7f9ff41` trataram adversários do Prove, compatibilidade de dados PC, elites elementais, zonas de Time Attack, adaptação de IA e aliases de assets. A existência de dados/carregamento não prova, por si só, que cada fase ou combate funcione.
- **15 nov — telas e progresso:** `88d5526` ajustou título genérico de grupo no HoE; `9b55f27` preservou visibilidade do cartão Prove no importador; `717d1ff` substituiu subtítulo provisório do resultado Time Attack; `fbb4f97` restaurou prévias de recompensa e rótulos de andar da Tower. O registro de Tower confirma visualmente o rótulo e prévia do andar 2, não o CP nem os demais andares.
- **15 nov — dados e fluxo:** `634dc5f` fechou dependências e metadados v1025; `cb9c36b` preservou o time ativo; `03feee3` corrigiu o binding de conclusão do chefe; `424dfab` restaurou valores/limites de bônus.
- **15 nov — tooltip:** `b3125dc4c5f5fa19292fa40927cda970a929bb4e` manteve o tooltip dentro do lobby; runtime usa tabelas v1027. O usuário confirmou os três textos após reload; revisão aprovou a decodificação 3.131/3.131, os três campos alterados e a preservação de resS.
- **85f9d17 — registro documental:** documentou contagens de estados do grafo do Goenitz; não é um novo checkpoint de código.

### Buff Select: progresso e regressões conhecidas

- As runs dos andares 1–3 confirmaram vitórias, recompensas, picks e continuidade de time/HP. No andar 5, save leu clear=5/max=5, run=6 e picks 4[1010]/5[1002]; isso registra avanço, não IA funcional.
- O usuário avançou voluntariamente até o andar 13. As três penalidades -10% foram observadas individualmente nos alvos, nos andares 11–13, e trocam/removem ao avançar (detalhes abaixo).
- **Bônus positivos:** no Rugal 1256, 64000010 ativo L1/stack 1 produziu +5% de crítico. O snapshot aprovado `live-player-buffs-20261115-123104.json` também registra no alvo do Rugal 1294 os modificadores empilhados 64000001 L2 key12=.10, 64000002 L1 key32=.06, 64000004 L2 key51=.06, Fury 64000007 L1 key699=.04 e 64000008 L2 key12=.20; registrar atividade dos modifiers sem extrapolar além do snapshot. Crítico técnico 1010 e defesa 1009 estavam inativos no Attack tipo 1, conforme seus alvos.
- **Goenitz (F5):** Monster 582013, visto parado e sem alvo; grafo 64 nós (5 Failure, 59 Resting) e 105 tasks (3 Success, 76 Resting, 26 sem status). TaskCondition_BuffownerNodeID0 tinha initSuccess=true; FindWithTag/ActionFindObject node 2 tiveram sucesso. Replay terminou por tempo; causa não estabelecida. TEMP: `goenitz-floor5-character-ai.json`, `goenitz-floor5-ai-running.json`, `snapshot-buff-floor5-goenitz-active.json`.
- **Krizalid (F10):** Monster 582020, AiGroup 845, prefab Character; parado a 100% HP em duas leituras, com alvo. FSM rodava; 29 nós (5 Failure, 23 Resting, 1 Success); Action_FindUser teve sucesso, ActionSkill node 28, init true, terminou em Failure. Sintoma diferente; investigar sequência/habilidade. TEMP: `npc-ai-20261115-122457.json`, `npc-ai-20261115-122514.json`.
- A barra Elite sem modelo aparente persiste no print do andar 5. Efeitos visuais dos buffs seguem em análise; nenhum efeito novo foi implementado. Pedido de remover indicadores Wi-Fi/bateria no cliente PC ainda não instalado.
- Nenhum dos dois defeitos de IA foi corrigido por Ghidra ou patch neste registro. Não há validação ampla de todos os andares; não se exige executar manualmente todas as 50 fases para manter essa lacuna declarada.

## Evidência por modo

| Modo | O que foi observado no cliente / registros reais | O que segue sem prova suficiente |
| --- | --- | --- |
| Hall of Elements | Vitórias registradas em Purple 1, 2, 32 e 33; Blue 1 com vitória, mas chefe sem identificação visual; chefe correto e vitória em Red 1; modelo, ondas atacando e vitória em Green 1; modelo e vitória em Yellow 1. A tela mostrou um cartão contendo cinco elementos com cores distintas. | Não há prova de 165 combates. IA individual de Yuri/King, restantes etapas/elementos e cobertura ampla do modo continuam pendentes. |
| Time Attack | Street Rumble (30101), três arenas, chefes/inimigos e vitória; resultado registrado em 01:02.999, rank 1, Frostty, 100 rubies e 80.000 gold; save mostrou 62.999. | Os outros oito desafios e fluxos/recompensas adicionais não foram validados. |
| Sura | Ninja Ambush: vitória, 22.000 gold, 20 rubies e first clear; save registrou desbloqueio do desafio 2. | Os outros 23 desafios. |
| Tower of Illusion | QE107, andar 1: inimigo atacou, vitória, 6.000 gold, 20 rubies e uma cápsula; andar 2 desbloqueado. Na v1025, tela do andar 2 mostrou Lv. 32 e prévia de 7.000 gold, 20 rubies e cápsula. | CP permanece 0 por lacuna de dados; os outros 49 andares não têm validação runtime registrada. |
| Buff Select | Vitórias registradas nos andares 1–5; HP/ATK/DEF -10% confirmados individualmente em amostras dos andares 11–13. | IA de Goenitz (F5) e Krizalid (F10) com defeitos observados; barra Elite sem modelo persiste. Não há validação ampla de todos os andares. |
| Prove | ModeTable com display=1 foi preparado/instalado; servidor fornece cinco adversários. Leitura de dois arrays de metadata confirma que nenhum expõe o índice 109 pela rota ChallengeTop. Scene 155 existe em outra rota do catálogo nativo. | Não foi comprovado que o card/tela Prove apareça ao usuário; ChallengeTop não expõe o índice 109 e a rota alternativa Scene 155 ainda não foi comprovada na UI. Nenhuma batalha foi validada. |
| Advent | Evento 42001 (Yashiro) abre a lista; selecionar termina em EventEndNotice e retorna ao hub. | Combate não testado. Emissor nativo da notificação ainda está em investigação; os outros eventos não foram testados em combate. |

## Penalidades negativas confirmadas

- **HP (64000103), andar 11:** Rugal 1294, target active L1/stack 1, key 22 (`MaxHPR`) = -0,10000000149; HP máximo observado 11→9. Evidência: `live-player-buffs-20261115-123104.json`. O snapshot 12:30:22 era anterior à aplicação no alvo; prevalece a leitura posterior de 12:31:04.
- **ATK (64000101), andar 12:** target active L1, key 12 = -0,10000000149; HP debuff anterior ausente de self/target. Evidência: `live-player-buffs-20261115-123345.json`.
- **DEF (64000102), andar 13:** target active L1, key 32 = -0,10000000149; ATK/HP debuffs anteriores ausentes. Evidência: `live-player-buffs-20261115-123641.json`. As amostras confirmam troca/remoção ao avançar; reservas 1339/1225 não confirmam efeito nos três personagens e combos 31/41 não foram medidos.

## Distinções que devem ser preservadas

- Correção aplicada ou dado presente é evidência estática/estrutural; instalação confirmada não é prova do efeito em batalha.
- Uma run real prova aquele fluxo e aquela condição. Não generalizar uma amostra para todas as fases, elementos, personagens ou recompensas.
- O buff defensivo 1009 não atuar em Andy/Alice (Attack, tipo 1) e Rugal (Technical, tipo 3) é compatível com alvo do tipo 2; isso não prova a aplicação em personagem do tipo correto.
- Os valores negativos 2001–2003 mapeiam para 64000101 (ATK), 64000102 (DEF) e 64000103 (HP), todos -10%. A tabela viva confirmou `svBase`, `svPerLv` e `svMax` = -0,10000000149 (5.827 linhas); evidência TEMP `native-analysis/cached-negative-buff-power-v1027.json`. A ativação e efeito em combate estão detalhados acima por andar.
- A auditoria comunitária sobre quantidade crescente de maldições por faixas de andares (11–30 uma, 31–40 duas, 41–50 três) é uma regra herdada de referência comunitária, ainda não confirmada como regra original da Netmarble.
- Não houve implementação de hot reload. Reinício continua necessário para carregar alterações de dados.
- O fake sign-in não foi removido por patch binário específico aprovado. A marca Frostty de 68% no banner é legado visual, não métrica atual auditada; não foi atualizada.
- Prints gerados têm limpeza autorizada posteriormente; preservação de prints do usuário, assets, logs e backups permanece necessária. Este registro não afirma que essa limpeza foi realizada.
