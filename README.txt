BIGSIXX48 — AI CLIPPER

Este pacote mantém a interface do app e inclui o serviço que faltava para
importar vídeos, reconhecer a fala e finalizar os cortes. Não é somente um HTML.

USAR NO CELULAR

Para usar os links do YouTube no celular, abra o endereço HTTPS de uma instalação
do serviço. A hospedagem precisa executar este pacote completo, incluindo
FFmpeg, yt-dlp e Python. O arquivo static/index.html aberto sozinho não instala
esse serviço: as restrições do navegador impedem baixar e editar o conteúdo de
um player incorporado do YouTube. O pacote não inclui uma hospedagem contratada.

HOSPEDAR

O Dockerfile e railway.json estão prontos para um serviço Docker no Railway.
Também é possível usar outra hospedagem que execute containers Python e permita
conexões de saída para o YouTube e para baixar o modelo de reconhecimento.
Selecione os arquivos deste pacote como fonte e publique o serviço Docker.
A aplicação respeita a variável PORT fornecida pela plataforma.
Reserve pelo menos 2 GB de RAM para começar; vídeos longos e modelos maiores
podem exigir mais memória, processamento e espaço. A hospedagem pode ter custo.

Configure armazenamento persistente em /app/.data para conservar vídeos,
exportações e o modelo de reconhecimento entre reinicializações. Sem ele,
esses arquivos podem ser perdidos quando o container for substituído.
O volume deve permitir gravação ao usuário do container (UID/GID 10001).
Cada instalação deve executar uma única instância do serviço: o estado dos
trabalhos em andamento fica na memória dessa instância.

INSTALAR EM UM COMPUTADOR COM DOCKER

1. Instale Docker com Docker Compose.
2. Abra um terminal nesta pasta e execute:
   docker compose up --build
3. Abra http://127.0.0.1:8000 no computador.

Para abrir no celular na mesma rede, use http://IP-DO-COMPUTADOR:8000 e mantenha
o computador ligado. O acesso pode depender do firewall da rede. O endereço
127.0.0.1 no celular aponta para o próprio celular, não para o computador.
Para acesso fora dessa rede, use uma instalação hospedada com HTTPS.

INSTALAR SEM DOCKER

Requisitos: Python 3.10 ou superior, FFmpeg e ffprobe no PATH. Para a importação
do YouTube, instale também Node.js 20 ou superior ou outro runtime suportado
pelo yt-dlp. As dependências Python são instaladas na pasta .venv.

Windows: execute iniciar.bat.
Linux/macOS: execute sh start.sh.
Abra http://127.0.0.1:8000 e mantenha o processo aberto enquanto usar o app.

RECONHECIMENTO DE FALA E ANÁLISE

Não exige uma chave de API de IA. O modelo Whisper multilingual tiny funciona
no processador. O primeiro uso baixa o modelo; essa etapa precisa de internet
e pode demorar. Depois, ele fica no cache. O download não acontece ao abrir
a interface, mas ao analisar um vídeo com áudio.

As legendas vêm do reconhecimento da fala presente no arquivo; elas podem
conter erros, principalmente em música, ruído ou falas sobrepostas. Vídeos sem
fala não recebem legendas inventadas. Os cortes e as notas são calculados a
partir de sinais do conteúdo, como áudio, movimento e correspondência com o
foco solicitado; a nota é uma comparação entre trechos, não uma garantia de
viralização ou uma previsão de desempenho em redes sociais.

Você pode definir WHISPER_MODEL=base ou small para usar um modelo maior.
Isso aumenta o download e o uso de memória/processamento. O cache do container
fica em /app/.data/models. Opcionalmente, baixe o modelo durante a construção:
   docker build --build-arg PRELOAD_WHISPER_MODEL=1 -t bigsixx48-clipper .

IMPORTAÇÃO DO YOUTUBE

Links watch, youtu.be, Shorts e lives gravadas são reconhecidos, incluindo
parâmetros de compartilhamento como ?si= e ?is=. O vídeo precisa estar disponível
para o servidor. Conteúdo privado, removido, com restrição de acesso ou bloqueado
para o endereço da hospedagem pode não ser importado. Nesses casos, o app
informa o erro; use o arquivo local do conteúdo autorizado ou outro vídeo.
Não é possível prometer que todo link do YouTube funcione em toda hospedagem.

ATUALIZAÇÃO E ARQUIVOS

Se mudanças do YouTube interromperem a importação, atualize o yt-dlp no ambiente
da instalação ou reconstrua a imagem com as dependências atualizadas.
Os arquivos ficam em .data/media, .data/exports e .data/work. Pare o serviço antes
de removê-los manualmente. Trabalhos em andamento não continuam após reiniciar.
