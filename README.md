# Conversor de Vídeos em Massa — Alta Eficiência (MP4)

Aplicativo desktop para Windows criado para comprimir e converter grandes quantidades de vídeos pesados para `.mp4`, reduzindo significativamente o tamanho dos arquivos enquanto preserva excelente qualidade visual — além de incluir **download direto do YouTube com vídeo + áudio funcionais em MP4**.

## Instalação Rápida no Windows (`.exe`)

- **Instalador completo:** execute `Instalador_Conversor_de_Videos.exe` (já traz o aplicativo, o desinstalador e o `ffmpeg.exe` embutidos). Ele instala em `%LOCALAPPDATA%\Programs\ConversorDeVideos`, cria atalhos no Menu Iniciar / Área de Trabalho e registra o programa no Windows.
- **Execução direta:** também é possível abrir `ConversorDeVideos.exe`, `Iniciar Conversor (Sem Console).vbs`, `Iniciar Conversor.bat` ou `python app.py`.

## Download de Vídeos do YouTube (Vídeo + Áudio MP4)

No topo da interface, cole a URL de um vídeo do YouTube e clique em **Baixar Vídeo + Áudio (MP4)**:
- O download usa `yt-dlp` integrado ao `ffmpeg.exe` local para baixar e mesclar as faixas de vídeo (`H.264`) e áudio (`AAC`) em um único arquivo `.mp4` reproduzível nativamente no Windows.
- Após o download, o sistema verifica automaticamente se o `.mp4` contém ambas as streams (vídeo e áudio) e padroniza o áudio para `AAC` caso necessário.

## Como Usar a Conversão em Massa

1. **Pasta com os Vídeos (Origem):** clique em **Selecionar Pasta...** e escolha a pasta onde estão seus vídeos grandes (suporta `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`, `.wmv`, `.flv`, `.m4v`, `.ts`, `.mts`, `.mpg`, `.mpeg`, `.3gp`).
2. **Pasta de Destino (Saída):** por padrão é sugerida uma subpasta `Convertidos_MP4` dentro da pasta de origem, ou você pode escolher qualquer outra pasta de saída.
3. **Escolha o Perfil de Eficiência (MP4):**
   - **MP4 • H.265 (HEVC) — Equilíbrio Ideal (Recomendado):** melhor relação entre qualidade visual preservada e redução de tamanho (normalmente reduz 40% a 65% em vídeos grandes).
   - **MP4 • H.265 (HEVC) — Alta Qualidade Visual:** ideal quando você quer manter nitidez máxima em gravações importantes.
   - **MP4 • H.265 (HEVC) — Máxima Economia de Espaço:** reduz o peso ao máximo mantendo boa legibilidade e qualidade.
   - **MP4 • H.264 (AVC) — Eficiência & Compatibilidade Universal:** compatível com praticamente 100% das TVs antigas, celulares, editores e navegadores.
   - **MP4 • H.264 (AVC) — Super Leve (Web / WhatsApp):** ótimo para compartilhamento rápido com compatibilidade total.
   - **MP4 • AV1 (AOM-AV1) — Eficiência de Última Geração:** compressão moderna avançada (conversão mais lenta, altíssima eficiência).
   - **MP4 • H.265 Rápido (GPU Intel QuickSync):** usa aceleração de hardware Intel QuickSync para converter bem mais rápido, com fallback automático para CPU se algum vídeo específico exigir.
4. **Opções Extras:**
   - **Resolução Máxima:** mantenha a resolução original ou limite para `1080p` / `720p` caso queira economizar ainda mais espaço em gravações 4K.
   - **Incluir subpastas:** processa também vídeos dentro de subpastas preservando a organização na pasta de saída.
   - **Pular vídeos já existentes:** permite retomar lotes grandes sem reconverter arquivos já prontos.
   - **Impedir que o vídeo final fique maior que o original:** evita que vídeos já muito comprimidos aumentem de tamanho.
5. Clique em **Iniciar Conversão em Massa** e acompanhe o progresso e a economia de espaço em tempo real.

## Executando a Partir do Código-Fonte

```powershell
pip install -r requirements.txt
python app.py
```

Para reconstruir os executáveis Windows (`.exe`):

```powershell
python build_exe.py
```
