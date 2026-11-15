# Status — restauração das sete dungeons

**Atualizado em 15/11/2026.** O checkout e seus registros atuais são a fonte de verdade. Este documento resume o ponto de retomada, cobertura real e próximos passos; detalhes do HoE estão em [`DIAGNOSTICO-HOE.md`](DIAGNOSTICO-HOE.md) e a cronologia temática em [`CHANGELOG-DUNGEONS.md`](CHANGELOG-DUNGEONS.md).

## De onde retomamos

O início histórico do trabalho foi o Hall of Elements voltar ao menu durante o carregamento/download e apresentar ausência de inimigos, conforme registrado em `DIAGNOSTICO-HOE.md`. O último checkpoint de código do escopo é `b3125dc4c5f5fa19292fa40927cda970a929bb4e` (`fix: keep Buff Select tooltips inside the lobby`), com runtime de tabelas v1027. O commit `85f9d17` é uma atualização documental histórica sobre a contagem da árvore de Goenitz, não um novo checkpoint de código. Antes dele, `424dfab` corrigiu os limites dos bônus, além das correções de conclusão, retenção do time e dados da Tower.

No registro do andar 5, o save indicava clear=5/max=5, run=6 e picks 4[1010]/5[1002]. O usuário alcançou o andar 13 e confirmou por amostra as três penalidades individuais nos andares 11–13. O Goenitz do andar 5 e o Krizalid do andar 10 permanecem com defeitos de IA observados.

`NOTA-ENTREGA.md` está disponível, mas é um handoff histórico de 14/11. Use-o com as ressalvas do diagnóstico atual; sua antiga afirmação de “Time Attack 100%” cobria navegação/endpoints, não batalha completa. `DIAGNOSTICO-HOE.md` contém a sequência recente de evidências.

## Progresso mensurável sem inflar o resultado

Uma métrica operacional estreita: **5 de 7 modos têm ao menos uma fase/rodada com fluxo completo de batalha e resultado registrado**, ou **71,4% dos modos com uma amostra integral**. São HoE, Time Attack, Sura, Tower of Illusion e Buff Select. Prove e Advent ainda não têm batalha validada.

Esse número não representa 71,4% das fases, dos dados, do trabalho total, da fidelidade ao jogo original ou da conclusão do projeto. Cada modo conta uma vez, mesmo que tenha dezenas de andares/desafios. É uma medida de presença de ao menos uma amostra integral por modo, útil para acompanhamento; sua cobertura continua muito desigual. O “68%” do banner Frostty é uma estimativa legada sem métrica atual e não deve ser usada como progresso verificado.

## Estado e continuação

| Modo | Resultado observado | Pendências principais |
| --- | --- | --- |
| Hall of Elements | Vitórias em amostras Purple 1/2/32/33, Blue 1, Red 1, Green 1 e Yellow 1. | Ampliar amostragem e verificar IA individual de Yuri/King; não há prova de 165 combates. |
| Time Attack | Street Rumble (30101), três arenas, vencido com resultado/save registrados. | Validar os outros oito desafios e continuidade/recompensas representativas. |
| Sura | Ninja Ambush vencido, first clear e desafio 2 desbloqueado. | Validar os outros 23 desafios por amostragem. |
| Tower of Illusion | Andar 1 vencido; andar 2 desbloqueado, com rótulo e prévia vistos em v1025. | CP do andar 2 segue sem dado; validar progressão e amostras dos outros 49 andares. |
| Buff Select | Vitórias registradas nos andares 1–5; usuário alcançou 13 e as três penalidades individuais foram confirmadas nos andares 11–13. | Goenitz (F5) e Krizalid (F10) ficaram parados; ambos sem correção. Barra Elite sem modelo persiste. Andares altos, efeitos visuais e combinações seguem parcialmente pendentes. |
| Prove | ModeTable display=1 preparado/instalado; servidor fornece cinco adversários. | Card/rota de UI não comprovados; ChallengeTop não expõe índice 109 e a rota Scene 155 segue incerta. Nenhuma batalha validada. |
| Advent | Evento 42001 (Yashiro) abre a lista e retorna ao hub via EventEndNotice. | Investigar emissor e viabilidade; nenhum combate validado. |

## Evidências recentes do Buff Select

- **Bônus positivos:** +5% de crítico confirmado no Rugal 1256 (64000010, nível/stack 1). Snapshot aprovado de 12:31:04 registra modificadores positivos empilhados e Fury no alvo de Rugal 1294; detalhes e campos estão no changelog. Buffs de crítico técnico 1010 e defesa 1009 estavam inativos no personagem Attack, como esperado. Efeitos visuais dos buffs estão em análise; nenhum efeito novo foi implementado.
- **Penalidades negativas:** HP 64000103 no andar 11, ATK 64000101 no 12 e DEF 64000102 no 13 foram confirmados individualmente no alvo, L1/−0,1, com a penalidade anterior deixando de aparecer ativa ao avançar. Referências: `live-player-buffs-20261115-123104.json`, `live-player-buffs-20261115-123345.json` e `live-player-buffs-20261115-123641.json`. Reservas 1339/1225 estavam apenas self-inactive; não há prova de aplicação nos três personagens nem de combos nos andares 31/41.
- **Goenitz após ajuste do gate:** `Monster|get_isHoldAnyUpdate` foi adaptado para `Actor`, mantendo os demais campos. Instalado e revisado, mas usuário confirmou que o chefe continua parado. Captura viva de 13:05:08: 21 Failure/43 Resting; Action_ReservedSkill do nó 42 falha. A correção permitiu avançar na árvore, sem resolver o combate.
- **Repetição de andares:** código e save confirmam nova escolha e picks duplicados após replay de andares já concluídos; correção em andamento, sem limpeza dos picks existentes.
- **HUD do PC:** usuário confirmou que Wi-Fi/bateria desapareceram após alteração de um byte no objeto PhoneInfo da interface de combate.
- **Goenitz antes do ajuste, andar 5:** sem alvo; 64 nós (5 Failure, 59 Resting), 105 tasks (3 Success, 76 Resting, 26 sem status). ActionFind teve sucesso; replay terminou por tempo. Causa não estabelecida. TEMP: `goenitz-floor5-character-ai.json`, `goenitz-floor5-ai-running.json`.
- **Krizalid, andar 10:** parado com 100% HP em duas leituras, com alvo; FSM rodava. Grafo 29 nós (5 Failure, 23 Resting, 1 Success); ActionSkill node 28 terminou em Failure. Sintoma distinto; causa não estabelecida. TEMP: `npc-ai-20261115-122457.json`, `npc-ai-20261115-122514.json`.
- **Tooltip e barra Elite:** usuário confirmou os três tooltips inteiros após reload; review do bundle aprovou decodificação e preservação. Barra Elite sem modelo aparente segue visível no print do andar 5 e pendente de investigação.

## Pendências transversais

1. Cobertura representativa dos elementos, fases, desafios e andares altos que faltam. Não é necessário executar manualmente todas as 50 fases; mantenha declaradas as lacunas sem extrapolar amostras. Preview não substitui combate real.
2. Medir efeitos, duração, alvos e empilhamentos que ainda não tenham cobertura suficiente; os limites nativos foram corrigidos. Resultados e limites por buff estão resumidos em “Evidências recentes do Buff Select” e no changelog.
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
