# Status — restauração das sete dungeons

Atualizado em 15/11/2026. Checkpoint de encerramento solicitado pelo mantenedor; tabelas v1034 instaladas. O histórico temático está em [CHANGELOG-DUNGEONS.md](CHANGELOG-DUNGEONS.md). [NOTA-ENTREGA.md](NOTA-ENTREGA.md) é histórico de 14/11 e não descreve a cobertura atual.

## Progresso comprovado

**6 de 7 modos têm pelo menos uma amostra com batalha e resultado completos:** Hall of Elements, Time Attack, Sura, Tower of Illusion, Buff Select e Prove. Advent ainda não tem combate validado. Isso não mede conclusão de fases, fidelidade ou porcentagem do projeto. **Não há porcentagem global defensável.** Os 68% do banner são uma estimativa antiga, sem métrica verificada.

| Modo | Comprovado | Pendente |
| --- | --- | --- |
| Hall of Elements | Purple 1/2/32/33 e amostras Red/Green/Yellow/Blue 1 vencidas; um card reúne cinco elementos. | IA Yuri/King; comprovar identidade Blue; cobertura representativa das 165 fases e dificuldades. |
| Buff Select | Progressão/vitórias; Goenitz F5 e Krizalid F10 com ataques continuados e vitória após v1029; bônus positivos e penalidades individuais HP/ATK/DEF em F11–13 medidos. Replay sem nova escolha; tooltip e remoção Wi-Fi/bateria confirmados pelo usuário. | Instalar/testar seis perfis NPC preparados; resolver Rock F25/Zero Clone F45; barra Elite sem modelo; alvos/combinações/empilhamentos nos andares altos. Não há validação dos 50 combates. |
| Time Attack | Vitórias relatadas em 30101, 30107 e 30109. | Outros seis desafios; continuidade e recompensas representativas. Navegação dos nove não comprova nove combates. |
| Prove | Transição VS corrigida; etapas 1/2 com vitórias registradas e 3 vencida pelo usuário. Progresso chegou a etapa 4/max 3. | Faixas de adversários, etapas 10/30, revanche, penalidades, recompensas e rota visual no menu. |
| Sura | Progressão até desafio 11; fever/vitória/recompensa/desbloqueio confirmados; Auto-Clear diário. Iori/Leona/Yashiro da primeira faixa atacam e foram vencidos; Yashiro Green confirmado em v1034. Repetição e first-clear validados após correção da recompensa. | Testar Chris/Shermie/Darkness; substituir chefes das faixas 2–4 ainda usando Asura; recuperar regras originais ausentes; ampliar cobertura. |
| Tower of Illusion | Andar 1 vencido, recompensa e desbloqueio do 2. | CP do segundo andar e amostras dos outros 49; progressão/recompensas. |
| Advent | Lista do evento 42001 abre; EventEndNotice devolve ao hub. | Corrigir entrada, validar combate/resultado/progressão. Alteração preexistente em gameapi.py preservada fora deste checkpoint. |

## Alterações recentes

- v1029: PG impedia a continuidade dos golpes NPC. Goenitz/Krizalid passaram a repetir ataques e vencer. Relatos anteriores de chefe parado ficam no changelog como histórico.
- v1030: Prove passou da transição VS para batalha/resultado. Automação temporária usa callbacks públicos do cliente na thread principal, com prontidão conferida antes de avançar resultados.
- v1031–1032: conexão e pesos de fever Sura corrigidos; usuário confirmou vitória/recompensa/progressão. Auto-Clear limitado a uma coleta por dia com persistência; horário/fuso exatos do reset original desconhecidos.
- v1033: +6 perfis Monster isolados e +121 MonsterSkill para a primeira faixa Sura, usando NPCs/skills existentes e referências originais. Curvas adaptadas ao consumidor Monster foram conferidas; isso não recupera tabelas originais ausentes. Iori/Leona/Yashiro observados atacando e vencidos; outros três ainda sem validação runtime.
- v1034: quatro valores de elemento do chefe corrigidos em QuestEventStageTable. Primeira faixa: Blue, Red, Green, Yellow, Purple, White. Elemento exigido do time é outra regra. Pack instalado decodificado/comparado ao master; 24 verificações do gerador de afinidades passaram.
- HUD Sura: barra fever abaixo do nome do chefe. Assets alterados por gerador; executável, originais e prefs preservados.

## Recompensa — ajuste final

O refresh manual anterior corrigia só a página aberta e o defeito voltava na vitória seguinte. O cliente retorna antes de inicializar o slot quando não há missões nem first-clear. Alterações de estados nos assets foram insuficientes e todas foram revertidas; nenhum candidato visual ineficaz foi mantido.

A correção final está em setup/client_compat.py, chamada por setup/launcher.pyw. Na build PC suportada, remove em memória o retorno antecipado de SetStarMission (JE de dois bytes, RVA 0x7F6F50), deixando o caminho nativo SetResultData(NULL, true, false) inicializar o estado recebido. First-clears reais já seguiam esse caminho; missões não nulas usam outro ramo. O SHA-256 do DLL em disco e uma janela de 24 bytes em memória são conferidos antes; byte inesperado recusa aplicação. Proteção da página é restaurada, cache de instruções atualizado e resultado relido. Não há alteração do DLL em disco, originais, assets, save ou prefs, nem dependência nova/serviço de monitoramento. Em falha, o launcher encerra somente o processo de jogo que acabou de criar e informa o erro.

Validação final em runtime, sem refresh manual: repetição do desafio 3 venceu e inicializou itemGroup=false/get=false/received=true, eliminando o template não configurado. A primeira vitória do desafio 11 manteve firstClear=1, Goods Ruby ×30, itemGroup=true/get=true/received=false; recompensas normais Gold ×50.000 e item 17002 ×4 preservadas. stageEnd confirmou vitória/ResultCode 0/FirstClearFlag 1; save avançou para clear=11/max=11 sem run pendente. A instrumentação temporária restaurou os bytes do Update após cada leitura; a compatibilidade de dois bytes permanece só na memória durante a execução. Referências locais de diagnóstico: root-reward-story-sid3-probe.json e root-reward-story-sid11-probe.json, em native-analysis TEMP. A conferência visual final após esta correção ficou para a retomada: o controle do computador não foi reativado após o mantenedor encerrá-lo. Não é validação de outros modos.

Usar play.cmd ou setup/launcher.pyw: a correção é reaplicada a cada inicialização por esse caminho. Abrir o executável diretamente ou um launcher externo que não use start_game não aplica essa compatibilidade. Não é hot reload geral. O DLL em disco permaneceu com SHA-256 6fc8a66893ddd282b9297c4cbe619b445c4121373fc2734e879faf4f5504c651; aplicação automática e idempotência foram verificadas, assim como recusa de instruções divergentes. Cache, save, prefs e backups ficam fora do Git.

## Fontes e fidelidade

- Cliente local: tabelas/bundles Windows, referência mobile disponível, logs, runtime e IDA/Ghidra. Análise estática não substitui ataques/vitória/recompensa observados.
- [Anúncio oficial Netmarble de Sura/Prove](https://ch.netmarble.com/Newsroom/PressRelease/Detail?bbs_code=1014&post_seq=1471), 08/06/2020: confirma os modos; não lista todos os chefes ou balanceamento.
- Gameplay original lido visualmente: [faixa 1](https://www.youtube.com/watch?v=-ezlyZN4Plw), [faixa 2](https://www.youtube.com/watch?v=-65jm892a1o), [faixa 3](https://www.youtube.com/watch?v=85wMgf6WxCI), [faixa 4](https://www.youtube.com/watch?v=FBqPaqyOEp8). Primeira faixa: Iori, Leona, Yashiro, Chris, Shermie, Darkness. Asura em todas as fases locais não reproduz esses vídeos.
- [Guia contemporâneo da comunidade](https://www.reddit.com/r/KOFALLSTAR/comments/j8rhlw/): seis desafios por faixa, coleta diária e restrição de retorno a faixas anteriores. Evidência complementar; as 24 linhas locais com penalidades de CP não são tabelas originais recuperadas.

## Retomada

1. Sura: demais perfis, faixas 2–4, regras e cobertura; conferir identidade/elemento/ataques/vitória/recompensa/progressão.
2. Buff Select e Prove: pendências da tabela, sem declarar todo o modo concluído por uma amostra.
3. Advent, Time Attack, Tower e HoE: combate pendente e cobertura representativa. Automatizar dependências/regras comuns e testes por perfil; não transferir 50 testes manuais ao mantenedor.
4. Especiais animados Kyo/Terry com dano zero: auditoria separada adiada pelo usuário. Hot reload não implementado; efeitos visuais de buffs não recuperados/validados como regra original.
5. Banner/porcentagem somente após definir métrica. Limpeza de capturas antigas ainda deve ser delimitada; preservar anexos do usuário, backups, originais e evidências necessárias.

Ao encerrar hoje: parar instrumentação/processos exclusivos dos testes, atualizar changelog e push. Meta incompleta, pausada a pedido do mantenedor para continuar amanhã.
