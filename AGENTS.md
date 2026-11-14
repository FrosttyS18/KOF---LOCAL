# AGENTS.md - KOF ALLSTAR Offline (projeto de preservação)

## 1. O que é este projeto

Cópia pessoal e local de The King of Fighters Allstar (cliente PC v1.17.0, Unity IL2CPP, build de jun/2024) rodando contra um servidor local em Python que substitui os servidores da Netmarble após o fim do serviço. Tudo roda em 127.0.0.1; nada vai online. Os arquivos do jogo pertencem à Netmarble/SNK: não compartilhar, não publicar, não enviar a serviços externos.

O jogo já funciona localmente hoje (`play.cmd`). As metas atuais, em ordem de prioridade:

1. Consertar bugs do projeto sem quebrar o que funciona.
2. Completar funcionalidades incompletas: modo história completo, dungeons e eventos.
3. Melhorar funcionalidades e a fidelidade das mecânicas ao jogo real.
4. Portar atualizações e mecânicas de versões mais atuais, somente quando os arquivos posteriores (cliente, tabelas, bundles) estiverem disponíveis. caso nao esteja tentar buscar na web formas de atualizar.

Regra transversal a tudo: **evitar regressões**. Entender o impacto do que está alterando antes de alterar; nenhuma solução vale quebrar o código, o jogo, o save ou o cliente.

## 2. Regra de processo: análise antes de implementar

Sem autorização explícita do mantenedor (ex.: `/start`), trabalhar somente em leitura, investigação, discussão e planejamento. Comandos de inspeção devem ser somente leitura.

- Antes de implementar, apresentar um plano curto: objetivo, arquivos/camadas afetados, comportamento a preservar, riscos relevantes e validações previstas. Esclarecer ambiguidades que mudem o resultado; não escolher silenciosamente entre interpretações.
- A autorização vale somente para o escopo alinhado. Mudança de escopo ou nova tarefa encerra a autorização; alinhar de novo.
- Operações sensíveis exigem explicação e aprovação específica, mesmo com autorização genérica em vigor: rodar `patch_client.py` (instalar ou remover o patch), trocar/restaurar contas (`account.py`, `new_game.py`), apagar ou mover saves, prefs, backups ou logs, alterar `state/options.json`, restaurar arquivos `.orig`.
- Não contornar restrições usando terminal, subagentes ou automações.

## 3. Fontes de verdade e fidelidade

- **O cliente é o oráculo.** `server/logs/requests-*.log` registra toda requisição (corpo criptografado e decodificado) e toda resposta; `server/logs/player.log` é o log do próprio jogo; `server/logs/story-requests.log` cobre o modo história. Antes de mudar um comportamento, ver o que o cliente realmente envia e espera.
- **Contrato de protocolo:** `server/api_map.json`, `server/api_types.json`, `server/tables/schema.json` e `server/tables/table_names.json` documentam tipos e campos.
- **O checkout atual é a fonte de verdade.** `PLAY.md` foi escrito na máquina de origem e cita caminhos e ferramentas que não existem neste pacote (`F:\...`, `relaunch.ps1`, `gen_*.py`, `PLAN.md`). Divergência entre documento e código: o código prevalece e a divergência deve ser relatada.
- **Mecânicas reais:** antes de recriar ou "consertar" uma mecânica, pesquisar na web o funcionamento real (guias da comunidade, wikis, vídeos da época do conteúdo) e reproduzi-lo fielmente. Separar o que foi OBSERVADO (logs/arquivos do cliente), INFERIDO (pesquisa) e o que permanece INCERTO. Não inventar dados do jogo: nomes, valores, taxas, drops, horários e recompensas vêm dos arquivos do cliente/tabelas ou de fonte confirmada; na falta deles, declarar a lacuna em vez de preencher com suposição.

## 4. Mapa do projeto

| Camada | Referências principais | Responsabilidade |
| --- | --- | --- |
| Entrada | `play.cmd`, `setup/launcher.pyw`, `setup/game_settings.reg` | Sobe o servidor local e o jogo (1280×720 padrão); na primeira execução importa as configurações do Windows. |
| Cliente do jogo | `game/KOF ALLSTAR.exe`, `GameAssembly.dll`, `game/KOF ALLSTAR_Data/` (inclui `global-metadata.dat`, `boot.config`, `Plugins/`), `game/NMSSW/` | Cliente Unity IL2CPP v1.17.0 patcheado. Cada arquivo alterado tem um `*.orig` ao lado. `NMSSW/` é o anti-cheat original, desativado via stub. |
| Servidor HTTP | `game/_preservation/server/kofserver.py` | Rotas na porta 18080: config de boot, packs de tabelas, CDN de bundles, SDK Netmarble (sign-in) e `/game/*`. |
| API do jogo | `game/_preservation/server/gameapi.py` + `ext_*.py` | ~115 handlers (`@api`); estado do jogador; cada sistema de jogo mais novo vive em seu `ext_*.py`, importado no fim do `gameapi.py`. |
| Lobby em tempo real | `game/_preservation/server/lobbytcp.py` | Servidor TCP na porta 18081 (presença/login; o tutorial de batalha depende dele). |
| Cripto | `game/_preservation/server/kofcrypto.py`, `server/keys.json` | AES-128-CBC: chaves do cliente (config, pcAuth, prefs) e a chave de tabela que o servidor entrega. |
| Tabelas | `server/tables/` (`data/`, `schema.json`, `hashes.json`), `tools/build_tables.py`, `tools/make_tablepacks.py`, `tools/tablepacks.py` | Master data reconstruído, criptografado e empacotado para o cliente. |
| Estado e contas | `server/state/` (`save.json`, `backup/`, `options.json`), `tools/account.py`, `tools/new_game.py`, `tools/prefs_edit.py` | Progresso do jogador, contas salvas, flags de teste. |
| Cache do cliente | `game/storage/cache/` (asset bundles, tabelas originais, `kofallstar.prefs`, `tablepacks.info`) | ~8,4 GB. Serve de CDN local; `kofallstar.prefs` guarda sessão/config do cliente. |
| Patches do cliente | `tools/patch_client.py`, `stubs/NMSSWBase.dll` | Aplica/remove os patches no cliente, com backup `*.orig`. |
| Python embutido | `python/` | Python 3.10.6 + pycryptodome. Nada precisa ser instalado; nada deve ser instalado nele. |

## 5. Contratos críticos entre camadas

Antes de tocar em qualquer ponto abaixo, conferir os dois lados do contrato; mudança incompatível exige plano aprovado:

- **Redirecionamento do cliente:** `global-metadata.dat` manda toda URL Netmarble/Facebook para `http://127.0.0.1:18080/<host>/<path>` e troca as pastas `table/common/` → `table/offline_common/` e `table/lang_` → `table/offline_lang_`. As tabelas originais em `storage/cache/table/` nunca são lidas nem sobrescritas.
- **Nomes e formato:** as respostas de `/game/*` são JSON plano com os nomes de campo C# que o cliente espera (Newtonsoft), mais `ResultCode`/`ResultMessage` de `WEBResponseBase`. Renomear um campo é quebrar o cliente.
- **Cripto:** chaves em `kofcrypto.py` (config, pcAuth) e `gameapi.py` (sessão AES/RC4, chave das prefs). O cliente só troca de chave se o servidor entregar outra na sessão; mudar chave exige atualizar todos os produtores e consumidores de uma vez.
- **Prefs do cliente (`kofallstar.prefs`):** o servidor reusa o `kNMPlayerID`/`kNMDeviceKey` salvos; um playerId diferente faz o cliente apagar todas as prefs. Não regenerar, não editar à mão (usar `tools/prefs_edit.py` se preciso) e nunca trocar o playerId sem plano.
- **Save (`state/save.json`):** criado por `session/create`, gravado atomicamente durante o jogo. Compatibilidade retroativa é obrigatória: um save antigo (e os backups) precisa continuar carregando após qualquer mudança de formato; mudança de formato exige tratar dados antigos, ausentes e inválidos.
- **Versão dos packs de tabela:** `TABLE_PACK_VERSION` em `kofserver.py` deve bater com a versão usada por `make_tablepacks.py` em `storage/cache/tablepacks.info` e com `version.kof`; e o `target` da config de boot deve igualar o `SelectedServer` das prefs, ou o cliente apaga o índice de packs.
- **Tabelas listadas vs. vazias:** `server/tables/hashes.json` lista só as tabelas reconstruídas; tabela listada = o cliente a descriptografa com a chave de `keys.json`; tabela não listada = o cliente a lê vazia, sem erro. Adicionar tabela nova exige rebuild (`build_tables.py`) e reinício de servidor e jogo.
- **CDN de bundles:** o manifest é derivado do `assetbundles.info` do próprio cache; nunca anunciar bundle sem arquivo correspondente (o CDN morto daria 404 e travaria o cliente). O comportamento especial de `fullbundles.snapshot` para o cliente Android deve ser preservado.
- **Cliente Android (opcional):** `state/options.json` (`androidFiles`) aponta para os arquivos de um dispositivo/émula na máquina de origem; nesta máquina o caminho não existe e essa via fica inerte. Não presumir que funciona aqui.
- **Patches do GameAssembly:** os quatro patches de código são específicos da build v1.17.0 (há checagem dos bytes originais). Os `*.orig` são a única cópia dos originais: nunca editar, mover ou apagar. O `NMSSWBase.dll` em `Plugins/x86_64/` é o stub do anti-cheat; o original está em `NMSSW/`.
- **Lobby TCP:** protocolo FreeNet (protobuf com XOR; após o login a chave de sessão é 16 bytes zero). O tutorial de batalha só sai da tela depois do login TCP bem-sucedido.

## 6. Conteúdo de versões posteriores

Quando arquivos de versões mais novas do jogo ficarem disponíveis (cliente, tabelas, asset bundles):

- Não presumir compatibilidade: patches de código precisam ser refeitos para a nova build (RVA/bytes originais), tabelas reconstruídas com `build_tables.py`, manifest de bundles regenerado a partir do novo `assetbundles.info`.
- Portar mecânica nova só com os dados dela em mãos (tabelas/bundles/strings); o que não existe nos arquivos não é inventado (ver seção 3).
- Manter o save e as prefs existentes funcionando; conteúdo novo não pode invalidar progresso atual.
- Validar em duas etapas: primeiro com o conteúdo novo isolado, depois com o save real do jogador.

## 7. Padrão de código

- Somente Python stdlib + pycryptodome já embutido. Não adicionar dependências, não instalar pacotes no `python/` do pacote, não criar ambientes virtuais.
- Preservar o estilo dos arquivos tocados: aspas duplas, docstrings em inglês explicando o comportamento do cliente (elas documentam a engenharia reversa e são parte do valor do projeto), indentação e organização existentes. Sem emojis. Comentários novos seguem o padrão dos existentes.
- Sistema de jogo novo ou ampliado vai em `ext_*.py` (ou novo `ext_*.py` com o mesmo padrão), registrado em `gameapi.py`; não inflar `gameapi.py` com código que tem responsabilidade própria.
- Não editar binários manualmente (`GameAssembly.dll`, `global-metadata.dat`, dlls, `.prefs`, caches): alterar o gerador/ferramenta correspondente e regenerar. Não editar `storage/cache/` à mão.
- Tratar erros explicitamente; falha de decode/parse vira log claro, não silêncio nem dado fictício. Ausência de medição/dado é ausência, não zero.
- Menor alteração correta: sem refatorações fora do escopo, sem reorganizar pastas, sem reformatar. Problema fora do escopo é relatado, não corrigido por conta própria.

## 8. Estado do jogador, contas e backups

- `state/save.json` é o progresso real do mantenedor; `state/backup/` guarda o histórico (pares `save-*.json` + `kofallstar-*.prefs`) e contas de teste. Nunca apagar, sobrescrever ou "limpar" backups para resolver incompatibilidade.
- `account.py` salva a conta atual antes de trocar; o jogo precisa estar fechado (ele escreve as prefs ao sair). Testes que mexem no estado devem preferir contas de teste (`account.py use test-...`) e voltar para `home` ao final.
- Flags de teste no save (`unlimited`, `allCores`, `allSpecialCards`, `ownAllFighters`) são lidas pelo servidor; mudar o significado delas afeta contas salvas antigas.
- Ao final de um trabalho que usou conta de teste, deixar a conta do mantenedor de volta no lugar.

## 9. Validação

Não há testes automatizados; a validação é manual e proporcional à mudança. Nunca afirmar que algo foi testado sem ter executado.

| Mudança | Validação mínima |
| --- | --- |
| `gameapi.py` / `ext_*.py` / `kofserver.py` | Reiniciar o servidor (`python\python.exe game\_preservation\server\kofserver.py`), jogar o fluxo alterado e conferir: nenhum `!! no handler` novo no log, `ResultCode` esperado, `player.log` sem exceções. |
| Tabelas (`tables/data`, `build_tables.py`, `make_tablepacks.py`) | Rebuild, reiniciar servidor e jogo, abrir as telas que leem as tabelas alteradas. |
| Prefs / contas / save | Com o jogo fechado: trocar de conta e voltar (`account.py use ...` / `home`), conferir que o save antigo carrega e nada foi perdido. |
| Patches do cliente (`patch_client.py`) | Só com aprovação específica; jogo fechado; após aplicar, abrir o jogo e exercitar o fluxo afetado; manter os `.orig` intactos. |
| Documentação | Revisar conteúdo, caminhos e comandos contra o código atual. |

Sempre que possível, rodar o jogo em janela (`play.cmd` padrão) e validar também um fluxo vizinho ao alterado (login, lobby, uma batalha, save contínuo) para checar regressão. Ao concluir, registrar o que foi validado e o que ficou pendente; validação pendente deve ser declarada, não omitida.

## 10. Versionamento (Git)

O projeto é versionado no repositório `FrosttyS18/KOF---LOCAL` (branch `main`). O versionamento cobre o que muda e pode regredir: código do servidor e ferramentas, tabelas reconstruídas, stub, configuração de boot do projeto e documentação.

- O `.gitignore` exclui deliberadamente: `python/` (interpretador embutido, de terceiros), `game/storage/` (cache do cliente e prefs, que contêm dados de sign-in), `game/_preservation/server/state/` (save atual, contas e backups), `logs/`, `*.orig` e todos os binários do jogo. Não "designorar" esses caminhos sem aprovação.
- Antes de começar um trabalho: `git status --short` e o diff relevante; separar mudanças existentes das suas; não sobrescrever trabalho não commitado.
- Commits pequenos e por tema (um bug, um sistema, um conjunto de tabelas), com mensagem que diga o quê mudou e por quê. Push ao concluir o escopo autorizado ou quando o mantenedor pedir.
- Nunca `reset --hard`, `clean`, descartar arquivos, forçar push ou reescrever histórico sem pedido específico. Não commitar arquivos fora do escopo da tarefa.
- O que o Git não protege: save do jogador, prefs, backups de contas e cache (estão ignorados). Backup desses dados é tarefa separada (copiar `server/state/` e `storage/cache/kofallstar.prefs`).

## 11. Comunicação e entrega

- Responder sempre em português do Brasil, de forma resumida, direta e objetiva.
- Ao concluir: **Alterado** (resultado e arquivos principais), **Validado** (comandos/fluxos realmente executados e resultados), **Pendente** (limitações e testes manuais pendentes, quando houver).
- Não apresentar suposição como fato; não prometer ausência de bugs; não esconder falhas.
- Concluída a tarefa autorizada, voltar ao estado de análise e aguardar novo escopo e autorização.
