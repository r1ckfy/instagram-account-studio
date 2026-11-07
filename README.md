# Instagram Account Studio

Aplicativo desktop para Windows 10/11 (Python + PySide6 + SQLite) para **organizar personagens
virtuais adultos (18+)**: importar fichas em TXT, associar e verificar e-mails do seu domínio, manter
perfis, abrir a página oficial do Instagram para **cadastro manual**, ler caixas de e-mail que você já
possui e acompanhar o status das contas.

> **Versão 1.3.0:** a aba NAVEGADOR abre Edge ou Chrome pelo painel e consegue fechá-los, e ganhou o campo Localização para copiar.
>
> **Versão 1.2.0:** nova aba **PROXY — diagnóstico de rede** (testes manuais de conexões HTTP, HTTPS e
> SOCKS5). O banco migra para o esquema v3, com backup automático antes.
>
> **Versão 1.1.0:** a aba DADOS passou a importar fichas por TXT (o gerador aleatório continua em
> "✦ Gerar ficha aleatória"), há e-mail associado com verificação e o banco migra sozinho para o
> esquema v2. Antes de migrar, o app grava `data\backups\antes_migracao_v1_<data>.db`.

## O que o app faz e o que não faz

| Faz | Não faz |
|---|---|
| Importa fichas de um TXT com prévia, validação e detecção de duplicadas | Não diz que um username está livre no Instagram (só confere o banco local) |
| Associa e-mails existentes e verifica DNS, regra da Cloudflare (leitura) e recebimento real | Não cria aliases, regras de encaminhamento nem registros DNS |
| Testa proxies cadastrados à mão: IP público observado, país/cidade aproximados, latência e autenticação | Não vincula proxies a personagens, não alterna IPs, não muda o proxy do Windows; configura apenas o navegador de diagnóstico isolado e não tem ligação com cadastro ou automação |
| Gera nomes, usernames, bios, datas de nascimento (18+) e senhas fortes | Não inventa endpoints: sem documentação da API do painel, não há criação de alias pela API |
| Salva, edita, duplica e exclui perfis com validação | Não preenche nem envia o formulário real do Instagram |
| Abre a página oficial de cadastro no navegador escolhido, com botões para copiar cada dado | Não contorna CAPTCHA, verificação, bloqueios nem limites |
| Lê caixas IMAP que você já tem (somente leitura) | Não cria e-mails nem apaga mensagens no servidor |
| Registra contas existentes e o histórico de status | Não marca uma conta como "Ativa" sozinho: só você confirma |
| Testa o preenchimento automático com Selenium **numa página demo local** | Não roda Selenium contra sites reais (`fill_demo` recusa outras URLs) |

## Requisitos

- Windows 10 ou 11
- Python 3.12+ ([python.org](https://www.python.org/downloads/)), com "Add python.exe to PATH" marcado
- Microsoft Edge (já vem no Windows) ou Google Chrome, para o teste demo com Selenium

## Executar

Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o `.venv` e instala as dependências.

Ou, pelo terminal:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Gerar o executável (.exe)

Dê dois cliques em **`build.bat`**. Ele:

1. verifica o Python;
2. instala as dependências;
3. roda os testes (o build para se algum falhar);
4. empacota com PyInstaller em modo pasta (`--windowed`);
5. confere se o `.exe`, a página demo e os modelos de exemplo existem;
6. mostra um resumo.

Resultado: `dist\InstagramAccountStudio\InstagramAccountStudio.exe`. Distribua a **pasta inteira**.
O modo pasta é mais compatível com o Qt e com o Selenium Manager do que um `.exe` único.

## Fluxo de uso

**IMPORTAR TXT → ASSOCIAR E-MAIL → VERIFICAR E-MAIL → APLICAR AO PERFIL → SALVAR → NAVEGADOR (abrir
página oficial e copiar os dados) → cadastro e verificações feitos por você → REGISTRAR RESULTADO →
acompanhar em CONTAS**

| Aba | Para que serve |
|---|---|
| **DADOS** | **IMPORTAR TXT** com prévia: cada ficha aparece como válida, com aviso, duplicada ou inválida, e você marca quais importar. Ao final sai um relatório (importadas, ignoradas, inválidas). A lista tem ID, nome, username, idade, localização, e-mail associado, status do e-mail e status do perfil, com busca e filtros. O painel direito mostra a ficha completa e tem SELECIONAR PERSONAGEM (abre no NAVEGADOR), EDITAR FICHA, ASSOCIAR E-MAIL, VERIFICAR E-MAIL, APLICAR AO PERFIL e REMOVER. O painel de baixo mostra o histórico de importações, erros de validação, resultados das integrações e alterações. Também tem EXPORTAR, Modelo de TXT e o gerador aleatório antigo. |
| **PERFIL** | Formulário completo com validação de username (regras do Instagram), e-mail, idade ≥ 18 e bio ≤ 150 caracteres. Salvar, limpar, recuperar o último, duplicar sem dados sensíveis, excluir e histórico de status. |
| **NAVEGADOR** | Escolha uma ficha (inclusive as importadas por TXT) e copie e-mail, nome, usuário, senha, nascimento, localização e bio. Escolha **Edge ou Chrome** e clique em **ABRIR PÁGINA DE CADASTRO**: o app abre `instagram.com/accounts/emailsignup/` para você preencher à mão, num perfil de navegador próprio do app (uma pasta só, `data
avegador`, a mesma para todas as fichas), separado do seu navegador do dia a dia. Por isso **■ FECHAR NAVEGADOR** encerra só essa janela. O painel percebe quando você fecha o navegador e registra abertura, encerramento e erros nos LOGS. **REGISTRAR RESULTADO** grava o desfecho. Sem navegação privada, sem proxy e sem perfil separado por ficha. O **teste demo** com Selenium continua com os estados AGUARDANDO → ABRINDO NAVEGADOR → CARREGANDO PÁGINA → PREENCHENDO CAMPOS → AGUARDANDO REVISÃO → CONCLUÍDO / INTERROMPIDO / FALHOU. |
| **IMAP** | Cadastre, teste e remova caixas de e-mail. Busca as mensagens recentes (data, remetente, assunto), filtra e lê o texto sob demanda. Mensagens do Instagram aparecem em ciano. |
| **PROXY** | Diagnóstico de rede. Cadastro de conexões HTTP, HTTPS e SOCKS5 (host/endpoint, porta, usuário, senha cifrada, fixo ou rotativo), **TESTAR CONEXÃO**, **TESTAR TODOS**, histórico de testes e erros, e importação/exportação sem senhas. Veja a seção abaixo. |
| **CONTAS** | Indicadores (total, ativas confirmadas, pendentes, falhas, última confirmada), busca, filtro por status, ordenação, edição, troca de status com observação, exclusão em lote e histórico. **＋ CONTA EXISTENTE** registra uma conta que você já criou. **⤓ Exportar** gera CSV (separado por `;`, abre direto no Excel), JSON ou TXT com os registros selecionados ou, sem seleção, com todos os listados pelo filtro. **As senhas não são exportadas**; elas ficam só no banco cifrado e nos backups. |
| **LOGS** | Terminal em tempo real com INFO, SUCESSO, AVISO e ERRO. Tem filtro por nível, busca, exportação em .txt, limpar, ir ao final, indicador de atividade e arquivo com rotação (`data\logs\studio.log`, 1 MB × 5). |
| **CONFIGURAÇÕES** | Banco (integridade, VACUUM, abrir pasta), backup e restauração, navegador (padrão, Edge ou Chrome), tempo para limpar senha copiada e **VERIFICAR SISTEMA**. |

### VERIFICAR SISTEMA

Faz checagens reais e mostra ✅ (confirmado), ❌ (falha) e ⚠️ (precisa de configuração):

- versão do Python, PySide6 e Selenium;
- integridade do SQLite;
- cofre DPAPI;
- permissão de escrita nas pastas de dados, logs e backup;
- presença da página demo;
- Edge e Chrome instalados;
- **inicialização real do driver** em modo headless;
- conexão com `www.instagram.com:443`;
- caixas IMAP configuradas.

## Formato do TXT de fichas

Um arquivo UTF-8. Cada ficha tem linhas `Campo: valor` e as fichas são separadas por uma linha `---`.
Modelo pronto: [exemplos/fichas_exemplo.txt](exemplos/fichas_exemplo.txt), ou o botão **Modelo de TXT**.

```
Nome: Rafaela Veloso
Usuario: rafavelo
Nascimento: 10/03/2004
Estado: Alagoas
Cidade: Maceió
Bio: |
  🌴 Influenciadora virtual
  Alagoana de coração
  22y
Email:
---
Nome: Lavínia Morelli
...
```

| Campo | Obrigatório | Também aceito como | Regras |
|---|---|---|---|
| Nome | sim | Nome completo | |
| Usuario | sim | Usuário, Username, User | formato do Instagram; `@` inicial é removido; maiúsculas viram minúsculas (com aviso) |
| Nascimento | um dos dois | Data de nascimento | DD/MM/AAAA, DD-MM-AAAA, DD.MM.AAAA ou AAAA-MM-DD; precisa ter 18+ |
| Idade | um dos dois | | número ≥ 18; se vier com Nascimento e não bater, vale o Nascimento (com aviso) |
| Estado, Cidade | não | UF | guardados exatamente como escritos |
| Bio | não | Biografia | `Bio: \|` abre um bloco de várias linhas; emojis e quebras de linha são preservados; mais de 150 caracteres gera aviso |
| Email | não | E-mail | se preenchido, precisa ser um endereço válido |
| Observacoes | não | Observações, Obs, Notas | |

O bloco aberto por `|` vai até a próxima linha **sem recuo** que comece com um campo conhecido, ou até o `---`.
Linhas com recuo dentro do bloco ficam como estão (o recuo comum é removido).

Duplicadas são detectadas por username, tanto dentro do arquivo quanto contra o banco, e não entram.
E-mail repetido ou já associado a outra personagem gera aviso e a ficha vem desmarcada na prévia.
Se o arquivo não estiver em UTF-8, o app aponta a linha do problema.

## E-mails do domínio (painel, Cloudflare e teste de recebimento)

### Status do e-mail

| Status | Significa |
|---|---|
| NÃO ASSOCIADO | a personagem não tem e-mail |
| ASSOCIADO | há um endereço ligado à personagem; nada foi verificado ainda |
| CONFIGURAÇÃO PENDENTE | a verificação achou um problema: sintaxe, sem MX ou sem regra de encaminhamento |
| ENCAMINHAMENTO CONFIGURADO | a Cloudflare confirmou uma regra ativa para o endereço (específica ou catch-all), ou você marcou manualmente |
| RECEBIMENTO TESTADO | uma mensagem de teste enviada para o endereço **chegou de fato** na caixa IMAP de destino |
| ERRO DE ENTREGA | a mensagem de teste não chegou em 10 minutos |

DNS e IMAP corretos **não** contam como entrega garantida. Só o teste de recebimento leva a RECEBIMENTO TESTADO.

### Configuração (CONFIGURAÇÕES)

- **GERADOR DE E-MAILS:** URL do painel (`https://painel.inboxnexo.online/`), URL base da API, tipo de
  autenticação, credencial (cifrada com DPAPI), domínio padrão (`inboxnexo.online`) e tempo limite. Os botões
  são TESTAR API, SALVAR CONFIGURAÇÃO, SINCRONIZAR ENDEREÇOS e DESCONECTAR.
  - A API do painel **não foi documentada**, então o app não presume endpoints. TESTAR API só confere se a
    URL informada responde e se a credencial é aceita.
  - Listar e criar aliases ficam em `app/email_infra.py` (`panel_list_addresses` / `panel_create_alias`),
    prontos para receber a implementação quando houver documentação.
  - Até lá, SINCRONIZAR ENDEREÇOS importa endereços de um TXT (um por linha) ou CSV (coluna `email`).
    Modelo: [exemplos/enderecos_exemplo.csv](exemplos/enderecos_exemplo.csv).
- **ENCAMINHAMENTO:**
  - Escolha a caixa IMAP de destino, a conta da aba IMAP que recebe o encaminhamento (ex.: o Gmail).
  - Opcionalmente, informe o Zone ID e um token da Cloudflare com permissão **Email Routing Rules: Read**.
    Com isso o app consulta, só para leitura, as regras de cada endereço e a regra catch-all.

### VERIFICAR E-MAIL (aba DADOS)

1. **Verificar configuração** checa:
   - a sintaxe do endereço;
   - o MX do domínio, por DNS-over-HTTPS (indica se aponta para Cloudflare Email Routing);
   - a regra de encaminhamento, se o token da Cloudflare estiver configurado;
   - a conexão IMAP com a caixa de destino.
2. **Teste de recebimento:**
   - **INICIAR TESTE** gera um código, como `IAS-1A2B3C4D`.
   - Você envia, de um endereço seu, um e-mail para o alias com esse código no assunto. O botão
     "Abrir no meu cliente de e-mail" já preenche a mensagem.
   - **VERIFICAR CAIXA** procura a mensagem na caixa de entrada e no spam da caixa de destino, em modo
     somente leitura.
3. Cada resultado fica registrado no histórico da aba DADOS e nos logs.

## PROXY — diagnóstico de rede

Módulo independente para testar manualmente conexões proxy que você cadastrou. Ele não se liga a
personagens, ao NAVEGADOR, ao Selenium nem ao cadastro.

- **Teste:**
  - Cada **TESTAR CONEXÃO** faz 3 requisições a `https://ipinfo.io/json` através do proxy, com tempo limite
    configurável. Roda em segundo plano, sem travar a interface.
  - Usa um pool de conexões próprio que é fechado ao final. Não altera o proxy do Windows, variáveis de
    ambiente. O navegador de teste tem configuração isolada.
- **O que aparece:**
  - IP público observado;
  - país, cidade e provedor aproximados (vêm de base de geolocalização);
  - latência média, mínima e máxima;
  - protocolo;
  - autenticação (OK, Recusada, Sem autenticação);
  - data da última verificação;
  - o IP sem proxy, para comparação;
  - histórico de testes e erros por conexão (os 200 mais recentes).
- **Classificação:**
  - ✅ **CONECTADO**: todas as amostras responderam e a latência mediana ficou abaixo de 3 s.
  - ⚠️ **INSTÁVEL**: alguma amostra falhou, a conexão está lenta, o IP mudou numa conexão cadastrada
    como fixa, ou o IP é o mesmo de sem proxy (o tráfego pode não estar passando pelo proxy).
  - ❌ **DESCONECTADO**: nenhuma amostra respondeu. O motivo aparece em português: conexão recusada,
    tempo esgotado, host não encontrado, erro de TLS ou senha recusada (HTTP 407 / SOCKS5).
- **Endpoint rotativo:** é cadastrado como qualquer outra conexão. IPs diferentes entre as amostras
  aparecem só como informação. O app não tem nenhuma ação de "trocar IP".
- **Protocolos:**
  - **HTTP**: proxy comum (túnel CONNECT para HTTPS);
  - **HTTPS**: TLS até o próprio proxy;
  - **SOCKS5**: o DNS é resolvido pelo proxy.
- **Segurança:**
  - A senha é cifrada com DPAPI e nunca aparece nos logs.
  - Com senha recusada, o teste para na primeira tentativa.
  - A exportação (JSON) não inclui senhas.
  - A importação aceita o JSON exportado ou um TXT com `[protocolo://][usuario@]host:porta` por linha.
    Senhas presentes no arquivo são descartadas, com aviso.
- **Bibliotecas:** usa `urllib3` com SOCKS (PySocks), que já vinham com o Selenium. Agora aparecem
  explicitamente no `requirements.txt`.

## E-mail (IMAP)

- **Gmail:** ative a verificação em 2 etapas e crie uma **senha de app** (Conta Google → Segurança → Senhas de app).
  Use `imap.gmail.com`, porta 993, SSL/TLS. Login OAuth2 **não** está implementado nesta versão.
- **Hostinger e outros domínios próprios:** `imap.hostinger.com`, porta 993, SSL/TLS, com o e-mail e a senha da caixa.
- **Outlook.com/Hotmail:** a Microsoft exige OAuth2 para IMAP, então não funciona nesta versão.
- O app **não cria endereços de e-mail**.
- A leitura é somente leitura (`SELECT` readonly e `BODY.PEEK`): nada é marcado como lido, movido ou apagado.
  Anexos não são baixados e o conteúdo das mensagens não fica salvo em disco.

## Segurança

- Senhas de perfis e de e-mail são cifradas com a **DPAPI do Windows** (`CryptProtectData`), presa ao usuário
  atual do Windows. Não há chave nem senha fixa no código. O banco e os backups nunca têm senhas em texto puro.
  Por isso, um backup só abre no mesmo usuário do Windows que o criou.
- Os logs registram ações e identificadores (username, nome da conexão), nunca senhas, tokens ou conteúdo de e-mails.
  Os testes conferem isso.
- A senha copiada sai da área de transferência depois de 30 s (ajustável em CONFIGURAÇÕES).
- O SQLite roda em modo WAL: transações confirmadas sobrevivem a um encerramento inesperado.

## Onde ficam os dados

`data\` ao lado de `main.py` (ou ao lado do `.exe`):

- `studio.db`: banco;
- `logs\`: logs;
- `backups\`: backups (pasta configurável).

## Testes

```bash
.venv\Scripts\python -m pytest -q
```

| Arquivo | Cobre |
|---|---|
| `test_generator.py` | usernames válidos em 1000 combinações, idade exata (inclusive 29/02), bio ≤ 150 em todo estilo e estado, força da senha |
| `test_db.py` | CRUD, duplicidade (sem diferenciar maiúsculas), histórico, estatísticas, backup/restauração, migração, senha nunca em texto puro no arquivo, exportação CSV/JSON/TXT sem senhas |
| `test_security.py` | ida e volta na DPAPI, blob adulterado rejeitado |
| `test_imap_parsing.py` | texto preferido ao HTML, anexos ignorados, decodificação de cabeçalhos, mensagens de erro |
| `test_logs_and_ui.py` | as 7 abas continuam presentes, importação TXT → ficha → APLICAR AO PERFIL → SALVAR, prévia da importação, associação com aviso de endereço repetido, importação de endereços, credencial cifrada; níveis de log, fluxo do gerador, filtro dos logs, bloqueio de duplicado, **senha ausente dos logs** |
| `test_fichas.py` | TXT com várias fichas, bio com emojis e quebras de linha, aliases de campos, CRLF, validação de obrigatórios, UTF-8 inválido, duplicadas no arquivo e no banco, gravação, atualização parcial, associação e status de e-mail, credenciais cifradas, **migração v1→v2 com backup** |
| `test_email_infra.py` | painel sem API e API fora do ar, códigos HTTP, Cloudflare (regra específica, catch-all, desativada, token inválido) via servidor HTTP local, MX por DoH, verificação completa, serviços offline, importação de endereços, IMAP: teste de conexão, busca do teste de recebimento (entrada e spam), porta fechada |
| `test_proxy.py` | **servidores locais reais** (serviço de IP, proxy HTTP com Basic Auth e proxy SOCKS5 com usuário/senha): conectado, senha recusada sem insistir, porta fechada, proxy mudo (timeout), endpoint rotativo × fixo, falhas parciais (instável), IP igual ao direto, nenhuma configuração de rede do sistema alterada, validação, exportação sem senha, importação TXT/JSON, senha cifrada no banco, histórico, sem vínculo com perfis e fluxo da aba PROXY sem travar a interface |
| `test_browser_managed.py` | comando do navegador (perfil próprio, sem modo privado nem proxy), abrir/fechar processo, navegador ausente, fluxo da aba NAVEGADOR (escolher Chrome, abrir, fechar pelo painel, detectar fechamento, logs sem senha) |
| `test_demo_fill.py` | Selenium headless preenche a página demo em duas etapas sem enviar, recusa outras URLs e acusa campo ausente. É pulado se não houver navegador ou driver. |

### Limitações conhecidas

- O teste Selenium só valida a página `demo\cadastro_demo.html`. O app não automatiza o site real do Instagram,
  que muda com frequência e proíbe criar contas por meios automatizados.
- Na primeira execução da demo, o Selenium Manager baixa o driver compatível, o que exige internet.
- O app não verifica se um username está livre no Instagram.
- Não há OAuth2 para Gmail ou Outlook nesta versão.
- Criação e listagem de aliases pela API do painel dependem da documentação da API.
- O diagnóstico de proxy depende de `ipinfo.io` estar acessível. O plano gratuito tem limite mensal de consultas.
  O modo HTTPS (TLS até o proxy) é coberto pelos novos testes de túnel TLS autenticado.
- A consulta de regras de encaminhamento depende de um token da Cloudflare. Sem ele, a regra pode ser
  marcada manualmente.

## Estrutura

```
main.py                 ponto de entrada
app/__init__.py         versão e caminhos
app/db.py               SQLite: esquema, migrações, CRUD, backup
app/security.py         DPAPI e gerador de senha forte
app/generator.py        gerador de dados e validações
app/fichas.py           leitura e validação do TXT de fichas
app/email_infra.py      DNS (DoH), Cloudflare (leitura), adaptador do painel, VERIFICAR E-MAIL
app/proxy_check.py      diagnóstico de proxies (testes manuais), importar/exportar sem senhas
app/browser.py          abrir páginas, Selenium (só a demo)
app/imap_client.py      IMAP somente leitura
app/diagnostics.py      VERIFICAR SISTEMA
app/logs.py             logging com rotação e ponte para a interface
app/ui/common.py        tema dark-tech, widgets e tarefas em 2º plano
app/ui/main_window.py   cabeçalho e abas
app/ui/tab_*.py         uma aba por arquivo
app/ui/dialogs.py       prévia da importação, editar ficha, associar e verificar e-mail
app/ui/gerador.py       gerador aleatório (diálogo)
app/ui/config_email.py  CONFIGURAÇÕES → gerador de e-mails e encaminhamento
demo/cadastro_demo.html formulário simulado para o Selenium
exemplos/               modelos de TXT de fichas e CSV de endereços
tests/                  pytest
```


Detalhes da integração real com Chrome/Edge, autenticação, isolamento e testes: [Navegador de diagnóstico de proxy](docs/PROXY_BROWSER.md).
## Central de Cadastros (atualização)

A aba **CENTRAL DE CADASTROS** usa as fichas do SQLite existente. Pesquise e selecione
uma ficha ou use **🚀 INICIAR CADASTRO AGORA** na aba DADOS para selecioná-la e iniciar.
A Central valida nome, usuário, e-mail, senha e nascimento, abre Chrome/Edge via Selenium
em segundo plano e carrega a página oficial. O aplicativo não preenche nem envia o
formulário do Instagram. CAPTCHA, confirmação de e-mail e cadastro são feitos pelo usuário.

O painel mostra os dados importados, senha protegida, dia/mês/ano separados, idade,
localização, bio e status. Há cópia individual, mostrar/ocultar senha, copiar próximo,
marcação manual de campos e reinício do checklist. Copiar não significa cadastrar.

A operação usa os estados PENDENTE, DADOS VALIDADOS, NAVEGADOR ABERTO, AGUARDANDO
USUÁRIO, AGUARDANDO VERIFICAÇÃO, CONCLUÍDO, FALHOU e INTERROMPIDO. Apenas REGISTRAR
RESULTADO, com confirmação humana, pode concluir o cadastro. A operação mantém a ficha
original como referência mesmo se outra ficha for visualizada. FECHAR NAVEGADOR,
VERIFICAR STATUS e REABRIR PÁGINA atuam na sessão Selenium da Central.

O histórico fica na nova tabela `signup_events`, com ID de operação, ficha, estados
anterior/novo, horário, resultado e observação. A migração é aditiva e cria backup de
bancos anteriores antes de alterar o esquema. As tabelas existentes não são substituídas.
As sessões de diagnóstico de proxy continuam separadas, sem proxy no cadastro.
O fluxo antigo da aba NAVEGADOR foi preservado e impede abertura concorrente com a Central.

A demonstração Selenium permanece na aba NAVEGADOR e funciona somente na página local.
Agora confere os valores inseridos, inclusive dia/mês/ano, e acusa divergências sem
registrar a senha. As dependências atuais são suficientes; Selenium Manager precisa de
um driver compatível e Edge/Chrome instalado. Nenhum sucesso de cadastro é inferido do site.

Testes novos: `tests/test_signup.py`. Relatório da abertura real pela interface:
`build/central-real-report.json`. Para utilizar o banco original, execute `iniciar.bat`.


### Preenchimento no Instagram (atualizacao)

A Central agora preenche automaticamente e-mail, nome completo, username e senha
na pagina oficial ao iniciar. Cada valor e conferido no DOM; nenhum formulario e enviado.
O botao PREENCHER CAMPOS DO INSTAGRAM repete a tentativa na mesma sessao, usando a
ficha original da operacao. Nascimento so e preenchido quando os seletores estiverem
visiveis; nao ha clique automatico em Avancar. Login, cookies ou verificacoes que
impecam o acesso ao formulario devem ser resolvidos pelo usuario antes de tentar novamente.
Campos ausentes aparecem no painel/historico. A confirmacao do resultado continua manual.
A aba NAVEGADOR antiga permanece com abertura manual e copia; o preenchimento automatico
real esta na CENTRAL DE CADASTROS e no botao principal da aba DADOS.

O teste de preenchimento usa Selenium contra formulario local, com campos reais e
verificacao de que nao houve submit; inclui campos ausentes e restricao de origem HTTPS.
