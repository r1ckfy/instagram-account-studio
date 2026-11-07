# Central de Cadastros — entrega

## Arquivos

- `app/signup.py`: validação e sessão Selenium isolada para navegação manual.
- `app/ui/tab_central.py`: Central, pesquisa, dados, checklist, estados e resultado confirmado.
- `app/ui/tab_dados.py`: botão principal integrado à ficha selecionada.
- `app/ui/main_window.py`: nova aba e encerramento coordenado.
- `app/ui/tab_navegador.py`: proteção contra operações concorrentes e fechamento do navegador gerenciado.
- `app/browser.py`: conferência dos valores preenchidos na demonstração local.
- `app/db.py`: migração aditiva v4, histórico por operação e consultas.
- `tests/test_signup.py`: cinco testes de validação, interface, DADOS, sessão, logs e persistência.
- `README.md`: instruções atualizadas. Nenhuma dependência nova necessária.

## Verificação

- Suíte completa: **141 aprovados** em 274,80 segundos.
- Verificação final dos cinco testes da Central: **5 aprovados** em 15,59 segundos.
- Os testes Selenium da demonstração local passaram, incluindo preenchimento, nascimento,
  envio humano da demonstração, recusa de outra URL e campo ausente.
- Teste real pela interface, com Edge visível e uma ficha existente: DADOS VALIDADOS →
  NAVEGADOR ABERTO → AGUARDANDO USUÁRIO. Encerramento confirmou liberação da sessão.
- Nenhum cadastro real foi preenchido ou enviado pelo aplicativo durante o teste.
- A confirmação humana do resultado foi testada automaticamente com um diálogo controlado.
  Não se afirma que uma conta real tenha sido criada.
- Banco real: integridade OK, cinco fichas e um proxy preservados. Migração v4 criou backup
  `data/backups/antes_migracao_v3_20261102_224355.db`.
- Evidência da sessão real: `build/central-real-report.json`.

## Uso e limites

Execute `iniciar.bat` para utilizar o banco já existente em `data/studio.db`.
Escolha a ficha em DADOS e clique INICIAR CADASTRO AGORA, ou use a própria Central.
O navegador da Central não utiliza os proxies de diagnóstico e não automatiza verificações.
O Selenium Manager precisa de Edge/Chrome e driver compatível. Chrome não está instalado
nesta máquina; o teste real utilizou Edge. A disponibilidade da página depende do Instagram.
O resultado real depende do preenchimento e confirmação do usuário.

Os primeiros testes identificaram métodos de histórico posicionados fora da classe Database;
isso foi corrigido antes da suíte completa. Nenhuma falha permaneceu nos testes finais.

Executável recompilado e atualizado em `dist/InstagramAccountStudio/InstagramAccountStudio.exe`.
A montagem foi feita em `build/central-release` e somente os arquivos do programa foram copiados
para a distribuição, sem apagar ou substituir sua pasta de dados. O arquivo empacotado foi
inspecionado para confirmar a inclusão de `app.signup`, `app.ui.tab_central` e `app.proxy_browser`.
