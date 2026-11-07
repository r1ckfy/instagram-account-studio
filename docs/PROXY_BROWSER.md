# Navegador de diagnóstico de proxy

Na aba PROXY, escolha uma conexão em SELECIONAR PROXY e o navegador Edge ou Chrome.
TESTAR CONEXÃO faz o diagnóstico Python existente. ABRIR NAVEGADOR DE TESTE valida o
cadastro, consulta o IP direto e testa o proxy/autenticação antes de iniciar uma janela
visível e isolada. VERIFICAR IP faz uma nova leitura da página no navegador e atualiza
o IP direto. FECHAR NAVEGADOR encerra o driver, as conexões e o perfil temporário.
Fechar a janela manualmente também dispara a limpeza. Fechar o aplicativo aguarda a
operação de proxy em andamento e limpa a sessão antes de fechar o banco.

O resultado do navegador vem do JSON exibido no corpo da página https://ipinfo.io/json,
lido pelo Selenium, com parâmetro para evitar cache. Não é o IP de uma requisição Python
apresentado como se fosse o do navegador. O painel exibe IP direto, IP do navegador,
protocolo, autenticação, tempo de carregamento e resultado; o histórico guarda a medição.
IPs iguais são classificados como INSTÁVEL, sem afirmar passagem confirmada pelo proxy.
Endpoints rotativos podem retornar IPs diferentes no preflight e no navegador.

## Transporte e autenticação

`app/proxy_browser.py` oferece uma ponte HTTP em 127.0.0.1, numa porta efêmera.
O Chrome/Edge usa somente essa ponte como proxy, sem alternativa DIRECT e sem bypass
de loopback. QUIC é desativado e WebRTC é limitado a UDP com proxy.
O perfil é temporário, exclusivo da sessão. Nenhuma configuração global do Windows,
variável de ambiente, conta ou ficha de Instagram é alterada.

- HTTP: túnel CONNECT para páginas HTTPS; autenticação Proxy-Authorization Basic.
- HTTPS: o mesmo protocolo sobre TLS até o proxy, com validação de certificado e hostname.
- SOCKS5: PySocks com DNS remoto e autenticação usuário/senha (RFC 1929).
- Páginas HTTP de diagnóstico GET são encaminhadas pelo mesmo upstream, com autenticação.
- A ponte é específica para diagnóstico; métodos HTTP sem implementação são recusados.
- Credenciais ficam em memória no serviço e cifradas por DPAPI no cadastro existente.
  Não entram em argumentos, URLs ou arquivos de extensão do navegador.
- Um upstream indisponível ou uma autenticação recusada gera falha; não há rota direta
  alternativa. Falha ao ler o IP no navegador encerra a sessão.
- HTTP Digest, NTLM, Kerberos e autenticação SOCKS GSSAPI não são implementados.
  O proxy precisa aceitar Basic (HTTP/HTTPS) ou usuário/senha SOCKS5.
- A ponte aceita conexões locais durante a sessão; ela não é um proxy de rede pública.
  O escopo é o tráfego de páginas do navegador de teste, não todos os serviços do Windows.

A autenticação SOCKS5 exige a ponte porque Chromium não implementa autenticação nesse
protocolo. Referências primárias:
https://chromium.googlesource.com/chromium/src/+/HEAD/net/docs/proxy.md
https://github.com/Anorov/PySocks
https://urllib3.readthedocs.io/en/stable/advanced-usage.html#proxies

## Testes e dependências

Usa as dependências existentes em requirements.txt. Selenium Manager localiza/obtém o
driver; Edge ou Chrome deve estar instalado. Chrome não foi encontrado nesta máquina.
Certificados privados de proxies HTTPS precisam de uma cadeia confiável para Python;
a aplicação nunca desativa a validação TLS.

`tests/test_proxy_browser.py` testa com sockets reais: HTTP/HTTPS CONNECT autenticado,
SOCKS5 com/sem senha, HTTP GET, credenciais recusadas, upstream indisponível, ausência
de fallback, fechamento da porta e limpeza ao fechar a janela. O teste TLS gera um
certificado local usando OpenSSL (Git for Windows); sem OpenSSL, somente esse caso é pulado.
O certificado é confiado somente pelo teste, sem alterar o armazenamento do Windows.

A medição pública real foi executada com Edge visível e o proxy cadastrado #1:
IP direto 131.100.73.191; navegador 45.185.154.106; autenticação OK;
1557 ms na primeira leitura e 232 ms na segunda. Esses valores são uma fotografia do
teste, não IPs fixos prometidos. O encerramento liberou navegador, ponte e perfil.
Relatório: build/proxy-real-report.json. Script reproduzível: build/test_proxy_real.py.

Validação adicional pelos botões reais da interface: IP direto 131.100.73.191;
IP do Edge 138.97.61.168; autenticação OK; 4195 ms na abertura e 1006 ms na nova
verificação. Fechamento manual detectado e recursos liberados.
Relatório: build/proxy-ui-report.json. Suíte completa: 137 testes aprovados.
