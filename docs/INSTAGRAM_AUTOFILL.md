# Preenchimento automático do Instagram

Atualização posterior ao fluxo manual original: a Central preenche os campos do formulário
oficial, mas não envia, não avança etapas e não resolve verificações.

A abertura pelo botão INICIAR CADASTRO AGORA agora carrega a ficha e preenche os campos.
PREENCHER CAMPOS DO INSTAGRAM permite tentar novamente na mesma janela e ficha original.
Os seletores reconhecem tanto o formulário tradicional, por nomes de campos, quanto o
formulário Meta atual, por labels associados, aria-label e comboboxes de nascimento.
Os valores são conferidos depois da digitação/seleção, com relatório de campos ausentes.
Não há escrita em login, challenge, domínios externos ou páginas HTTP.

Teste real com Edge e ficha #5: e-mail, nome completo, username, senha, dia, mês e ano
preenchidos e conferidos. Lista de campos ausentes vazia. Nenhum envio automático.
Sessão de teste encerrada após a leitura. Evidência sem credenciais:
`build/instagram-autofill-real.json`.

A primeira tentativa encontrou um formulário Meta sem os atributos name tradicionais.
Os seletores foram corrigidos usando a inspeção do formulário atual e o teste real repetido
com sucesso. A aba NAVEGADOR antiga mantém seu fluxo manual; utilize a Central ou o botão
da aba DADOS para preenchimento automático. Cookies e verificações continuam sob controle
humano; se impedirem acesso aos campos, resolva na janela e repita o preenchimento.

Arquivos: `app/instagram_fill.py`, `app/signup.py`, `app/ui/tab_central.py`,
`tests/test_instagram_fill.py`, `tests/test_signup.py`, `README.md`.

Verificação final: **17 testes aprovados** em 34,49 segundos, incluindo formulário
tradicional, campos sem name, comboboxes de nascimento, origem restrita, campos ausentes,
integração da Central e preservação da demonstração local.
