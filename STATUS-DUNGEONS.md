# Status — restauração das sete dungeons

**Atualizado em 15/11/2026.** O checkout e seus registros atuais são a fonte de verdade. Este documento resume o ponto de retomada, cobertura real e próximos passos; detalhes do HoE estão em [`DIAGNOSTICO-HOE.md`](DIAGNOSTICO-HOE.md) e a cronologia temática em [`CHANGELOG-DUNGEONS.md`](CHANGELOG-DUNGEONS.md).

## De onde retomamos

O início histórico do trabalho foi o Hall of Elements voltar ao menu durante o carregamento/download e apresentar ausência de inimigos, conforme registrado em `DIAGNOSTICO-HOE.md`. O último checkpoint atual é `b3125dc4c5f5fa19292fa40927cda970a929bb4e` (`fix: keep Buff Select tooltips inside the lobby`), commitado e enviado; HEAD e `origin/main` estão nesse checkpoint. A sequência anterior incluiu `424dfab` (`fix: restore Buff Select bonus values and power limits`), além das correções de conclusão do Buff Select, retenção do time e dados da Tower.

O save mais recente registra clear=5/max=5, run=6, picks 4[1010] e 5[1002]. O usuário encontrou o Goenitz do andar 5 parado, derrotou-o e avançou; isso confirma o progresso salvo, mas não a IA correta nem a validação plena do modo. Um replay do andar 5 também ficou parado e terminou por tempo. O bônus numérico real observado em teste anterior foi +5% de chance crítica no Rugal 1256, para o buff 64000010 ativo em nível/stack 1. O usuário confirmou os textos dos três tooltips inteiros após reload e planeja avançar até o andar 11 para medir HP negativo; esse teste ainda não foi concluído.

`NOTA-ENTREGA.md` está disponível, mas é um handoff histórico de 14/11. Use-o com as ressalvas do diagnóstico atual; sua antiga afirmação de “Time Attack 100%” cobria navegação/endpoints, não batalha completa. `DIAGNOSTICO-HOE.md` contém a sequência recente de evidências.

## Progresso mensurável sem inflar o resultado

Uma métrica operacional estreita: **5 de 7 modos têm ao menos uma fase/rodada com fluxo completo de batalha e resultado registrado**, ou **71,4% dos modos com uma amostra integral**. São HoE, Time Attack, Sura, Tower of Illusion e Buff Select. Prove e Advent ainda não têm batalha validada.

Esse número não representa 71,4% das fases, dos dados, do trabalho total, da fidelidade ao jogo original ou da conclusão do projeto. Cada modo conta uma vez, mesmo que tenha dezenas de andares/desafios. É uma medida de presença de ao menos uma amostra integral por modo, útil para acompanhamento; sua cobertura continua muito desigual. O “68%” do banner Frostty é uma estimativa legada sem métrica atual e não deve ser usada como progresso verificado.

## Estado e continuação

| Modo | Estado observado | Pendente prioritário |
| --- | --- | --- |
| Hall of Elements | Vitórias em amostras Purple 1/2/32/33, Blue 1, Red 1, Green 1 e Yellow 1. Blue sem identificação visual do chefe; Green teve modelo e ondas atacando. | Verificar elementos/fases restantes por amostragem representativa; validar IA individual de Yuri/King; não declarar 165 combates. |
| Time Attack | Street Rumble (30101), três arenas, vencido com resultado e save registrados. | Validar os outros oito desafios e recompensas/continuidade representativas. |
| Sura | Ninja Ambush vencido; first clear e desafio 2 desbloqueado. | Validar os outros 23 desafios por cobertura representativa. |
| Tower of Illusion | Andar 1 vencido; andar 2 desbloqueado. Prévia e rótulo Lv. 32 do andar 2 vistos em v1025. | CP do andar 2 continua sem dado comprovado; validar progressão e amostras dos outros 49 andares. |
| Buff Select | Andares 1–5 têm progresso/vitórias registrados no save; andares 1–3 também têm as runs detalhadas de recompensas, picks, HP/time e bônus 64000010 em Rugal. Andar 6 liberado; no andar 5, pick 1002 registrado. | **Prioridade alta:** Goenitz Lv. 40 do andar 5 foi visto parado com cinco barras; replay 5 também terminou por tempo. Capturas live mostraram FSM no estado CharacterAISample e árvore de IA em execução, sem alvo; no grafo, 5/64 nós estavam em Failure e 59/64 em Resting. Das 105 tasks, 3 estavam em Success, 76 em Resting e 26 sem campo de status. TaskCondition_BuffownerNodeID0 tinha initSuccess=true; FindWithTag/ActionFindObject da node 2 tiveram Success (`goenitz-floor5-character-ai.json`, `goenitz-floor5-ai-running.json`; snapshot `snapshot-buff-floor5-goenitz-active.json`). Save confirma clear=5/max=5/run=6 e picks 4[1010]/5[1002], logo avanço registrado não equivale a modo plenamente validado. Investigar IA do chefe. Barra Elite sem modelo aparente reapareceu no print do andar 5: defeito visual persistente, pendente de investigação/correção. Medir os demais bônus/efeitos e stacks; usuário planeja avançar até o andar 11 para medir HP negativo, ainda pendente. Valores negativos estão carregados no BuffTable vivo (5.827 linhas; -0,1 em base/per-level/max), mas redução efetiva de HP/ATK/DEF segue sem prova em combate. |
| Prove | ModeTable com display=1 preparado/instalado; servidor fornece cinco adversários. Dois arrays de metadata lidos não expõem o índice 109 pela rota ChallengeTop; Scene 155 existe em rota alternativa do catálogo. | Card/tela ainda não comprovado ao usuário. ChallengeTop não expõe 109; rota alternativa pela Scene 155 ainda não foi comprovada. Batalha não validada. |
| Advent | Evento 42001 abre a lista e volta ao hub por EventEndNotice. | Investigar emissor da notificação e viabilidade; nenhum combate do 42001 ou de outros eventos testado. |

## Pendências transversais

1. Cobertura por amostras dos demais elementos/fases, dos andares altos 5/10/50 e desafios ainda não exercitados. Não confundir níveis de referência no preview com combate real.
2. Medir em runtime valores numéricos restantes: bônus positivos, penalidades negativas, empilhamento, duração e alvos. O limite nativo foi corrigido com `Max := PerLv * MaxLevel` nas 18 referências; o crítico 64000010 foi medido em combate. Os valores negativos 64000101/102/103 foram lidos no BuffTable vivo com -0,1 nos três campos, evidência `native-analysis/cached-negative-buff-power-v1027.json`; isso não demonstra aplicação em combate.
3. Investigar/corrigir a barra Elite sem modelo aparente, novamente observada no print do andar 5. O defeito visual persiste; vitória do chefe não o resolve.
4. Reentradas, HP e time entre andares, recompensas, first clears e segurança de combate; realizar checks de regressão vizinhos conforme o fluxo de validação do projeto.
5. Confirmar se a rota alternativa do Prove pela Scene 155 pode ser alcançada pela UI; a rota ChallengeTop não expõe o índice 109. Investigar EventEndNotice e combate Advent.
6. Hot reload não existe; alterações de conteúdo ainda requerem reiniciar. Reavaliar o banner apenas depois de validação mais ampla e de definir uma métrica reproduzível.

## Origem dos dados e classificação das afirmações

- **Observado no cliente:** telas, ataques, vitórias, escolhas, recompensas, save e valores de buff ao vivo conforme registros existentes. As fontes concretas estão descritas no diagnóstico (prints do usuário, requests/save e leituras live); não se extrapola além da amostra.
- **Inspecionado estaticamente:** tabelas mobile importadas, bundles Windows locais, código/estruturas Unity e análise nativa anterior em IDA e atual read-only em Ghidra, adaptadores e verificadores. Isso fundamenta reconstrução e causalidade técnica, mas não substitui runtime.
- **Referência comunitária:** auxilia hipótese de mecânica, mas a regra de maldições por faixa de andar ainda não é prova de comportamento original Netmarble.
- **Limitação de plataforma:** assets Android não são copiáveis como assets Windows. Cache, save, prefs, logs e binários locais do jogo são dados preservados, não fontes para publicação/commit.

## Regras para atualizar este status

Só elevar o estado após evidência compatível com a afirmação: tela/código é evidência visual/estática; request e save confirmam registro de resultado; combate real confirma efeito apenas para o cenário observado. Registrar datas sem inventar horários, apontar o identificador da evidência quando existente e declarar lacunas. Não usar o banner “68%” como métrica nem afirmar cobertura total do jogo.
