// Uso: node diagnostico-chromium.cjs "C:\caminho\chromium.exe"
const { resolve } = require('node:path');
const { statSync } = require('node:fs');

async function main() {
  const supplied = process.argv[2];
  if (!supplied) throw new Error('Informe o caminho do executável do Chromium.');
  const executablePath = resolve(supplied);
  if (!statSync(executablePath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error('Executável do Chromium não encontrado.');
  }

  const { chromium } = require('playwright');
  const browser = await chromium.launch({ executablePath, chromiumSandbox: true, headless: false });
  try {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    try {
      await context.route('**/*', route => route.abort());
      const page = await context.newPage();
      await page.setContent('<title>Teste local do Chromium</title><h1>Canvas, WebGL e áudio</h1>');
      const report = await page.evaluate(async () => {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 4;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.fillStyle = '#13bf66';
          ctx.fillRect(0, 0, 4, 4);
        }
        const graphics = document.createElement('canvas');
        const gl = graphics.getContext('webgl2') || graphics.getContext('webgl');
        let audioRendered = false;
        if (typeof OfflineAudioContext === 'function') {
          const audio = new OfflineAudioContext(1, 1024, 44100);
          const tone = audio.createOscillator();
          tone.connect(audio.destination);
          tone.start();
          const rendered = await audio.startRendering();
          audioRendered = rendered.getChannelData(0).some(sample => sample !== 0);
        }
        return {
          canvas: ctx !== null && ctx.getImageData(0, 0, 1, 1).data[3] === 255,
          webgl: gl ? gl.getParameter(gl.VERSION) : null,
          audioRendered,
        };
      });
      console.log(JSON.stringify(report, null, 2));
    } finally {
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  const message = error.code === 'MODULE_NOT_FOUND'
    ? 'Instale Playwright com npm install playwright.'
    : error.message.split('\n')[0];
  console.error(message);
  process.exitCode = 1;
});
