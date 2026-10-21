// Assemble the ImageGen keyframes into a transparent, infinitely looping APNG.
// Usage: node scripts/build-lumo-avatar.cjs [source-sheet.png]
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = path.resolve(process.argv[2] || path.join(root, 'docs/assets/lumo-avatar-loop-v3-source.png'));
const output = path.join(root, 'apps/renderer/public/assets');
const review = path.join(root, '.tmp/lumo-avatar-animation');

if (!process.versions.electron) {
  const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE;
  const child = require('node:child_process').spawn(require('electron'), [__filename, source], { env, stdio: 'inherit' });
  child.on('error', error => { console.error(error); process.exitCode = 1; });
  child.on('exit', code => { process.exitCode = code ?? 1; });
} else {
  const { app, BrowserWindow } = require('electron');
  const crcTable = Array.from({ length: 256 }, (_, i) => {
    for (let k = 0; k < 8; k++) i = i & 1 ? 0xedb88320 ^ (i >>> 1) : i >>> 1;
    return i >>> 0;
  });
  function chunk(type, data) {
    const bytes = Buffer.concat([Buffer.from(type), data]);
    let crc = 0xffffffff;
    for (const b of bytes) crc = crcTable[(crc ^ b) & 255] ^ (crc >>> 8);
    const head = Buffer.alloc(4), tail = Buffer.alloc(4);
    head.writeUInt32BE(data.length); tail.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
    return Buffer.concat([head, bytes, tail]);
  }
  function decodePng(dataUrl) {
    const bytes = Buffer.from(dataUrl.split(',')[1], 'base64');
    const chunks = [];
    for (let p = 8; p < bytes.length;) {
      const length = bytes.readUInt32BE(p);
      chunks.push({ type: bytes.toString('ascii', p + 4, p + 8), data: bytes.subarray(p + 8, p + 8 + length) });
      p += length + 12;
    }
    return { bytes, header: chunks.find(c => c.type === 'IHDR').data, pixels: Buffer.concat(chunks.filter(c => c.type === 'IDAT').map(c => c.data)) };
  }
  function encodeApng(images, durations) {
    const frames = images.map(decodePng);
    if (frames.some(f => !f.header.equals(frames[0].header))) throw new Error('All animation frames must have identical PNG headers');
    const animation = Buffer.alloc(8); animation.writeUInt32BE(frames.length); // Zero plays means infinite loop.
    const parts = [Buffer.from([137,80,78,71,13,10,26,10]), chunk('IHDR', frames[0].header), chunk('acTL', animation)];
    let sequence = 0;
    frames.forEach((frame, index) => {
      const control = Buffer.alloc(26);
      control.writeUInt32BE(sequence++, 0);
      frame.header.copy(control, 4, 0, 8);
      control.writeUInt16BE(durations[index], 20); control.writeUInt16BE(1000, 22);
      // Full-canvas SOURCE replacement avoids trails around transparent moving hands.
      control[24] = 0; control[25] = 0;
      parts.push(chunk('fcTL', control));
      if (!index) parts.push(chunk('IDAT', frame.pixels));
      else { const seq = Buffer.alloc(4); seq.writeUInt32BE(sequence++); parts.push(chunk('fdAT', Buffer.concat([seq, frame.pixels]))); }
    });
    parts.push(chunk('IEND', Buffer.alloc(0)));
    return Buffer.concat(parts);
  }
  app.whenReady().then(async () => {
    app.dock?.hide();
    const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
    try {
      fs.mkdirSync(review, { recursive: true });
      const dataUrl = 'data:image/png;base64,' + fs.readFileSync(source).toString('base64');
      await win.loadURL('data:text/html,<html><body></body></html>');
      const result = await win.webContents.executeJavaScript(`(${assembleFrames.toString()})(${JSON.stringify(dataUrl)})`);
      const apng = encodeApng(result.frames, result.durations);
      fs.writeFileSync(path.join(output, 'lumo-avatar-loop-v3.png'), apng);
      fs.writeFileSync(path.join(output, 'lumo-avatar-loop-v3-still.png'), decodePng(result.keys[0]).bytes);
      result.keys.forEach((frame, i) => fs.writeFileSync(path.join(review, `key-${String(i + 1).padStart(2, '0')}.png`), decodePng(frame).bytes));
      fs.writeFileSync(path.join(review, 'contact-sheet.png'), decodePng(result.contactSheet).bytes);
      fs.writeFileSync(path.join(review, 'metadata.json'), JSON.stringify({ ...result.metrics, frames: result.frames.length, durationMs: result.durations.reduce((a,b) => a+b,0), loop: 0, bytes: apng.length }, null, 2));
      console.log(fs.readFileSync(path.join(review, 'metadata.json'), 'utf8'));
      win.destroy(); app.exit(0);
    } catch (error) { console.error(error); win.destroy(); app.exit(1); }
  });
}

async function assembleFrames(dataUrl) {
  const image = new Image(); image.src = dataUrl; await image.decode();
  const canvas = (w, h = w) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
  const sourceCanvas = canvas(image.width, image.height), sourceContext = sourceCanvas.getContext('2d');
  sourceContext.drawImage(image, 0, 0);
  const size = 192, keyframes = [], bounds = [];
  for (let index = 0; index < 12; index++) {
    const x = Math.round(index % 4 * image.width / 4), y = Math.round(Math.floor(index / 4) * image.height / 3);
    const w = Math.round((index % 4 + 1) * image.width / 4) - x;
    const h = Math.round((Math.floor(index / 4) + 1) * image.height / 3) - y;
    const tile = canvas(w, h), ctx = tile.getContext('2d');
    const pixels = sourceContext.getImageData(x, y, w, h), data = pixels.data;
    for (let p = 0; p < data.length; p += 4) {
      const r = data[p], g = data[p+1], b = data[p+2];
      const green = Math.max(0, g - Math.max(r, b));
      let alpha = Math.max(0, 1 - green / 255);
      if (g > 170 && r < 65 && b < 65 || alpha < .08) alpha = 0;
      if (alpha < 1 && alpha > 0) {
        data[p] = Math.min(255, r / alpha);
        data[p+2] = Math.min(255, b / alpha);
        data[p+1] = Math.min(data[p], data[p+2], Math.max(0, (g - 255 * (1 - alpha)) / alpha));
      }
      data[p+3] = Math.round(alpha * 255);
    }
    // Keep the connected character and discard any detached background specks.
    const seen = new Uint8Array(w*h); let largest = [];
    for (let i = 0; i < seen.length; i++) {
      if (seen[i] || data[i*4+3] < 20) continue;
      const component = [i]; seen[i] = 1;
      for (let p = 0; p < component.length; p++) {
        const j = component[p], px = j % w, py = Math.floor(j / w);
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const nx = px + dx, ny = py + dy, n = ny*w+nx;
          if (nx < 0 || nx >= w || ny < 0 || ny >= h || seen[n] || data[n*4+3] < 20) continue;
          seen[n] = 1; component.push(n);
        }
      }
      if (component.length > largest.length) largest = component;
    }
    if (largest.length < w*h*.12) throw new Error('Missing mascot in cell ' + (index + 1));
    const keep = new Uint8Array(w*h); largest.forEach(i => keep[i] = 1);
    let left = w, top = h, right = 0, bottom = 0;
    for (let i = 0; i < keep.length; i++) {
      if (!keep[i]) { data[i*4+3] = 0; continue; }
      const px = i % w, py = Math.floor(i / w);
      left = Math.min(left, px); top = Math.min(top, py); right = Math.max(right, px+1); bottom = Math.max(bottom, py+1);
    }
    ctx.putImageData(pixels, 0, 0);
    // Register on the lower shirt, which stays still while the head and hands move.
    let torsoX = 0, torsoPixels = 0;
    for (let py = Math.round(bottom - (bottom-top)*.13); py < bottom; py++) for (let px = left; px < right; px++) {
      const p = (py*w+px)*4;
      if (data[p+3] > 200 && Math.min(data[p], data[p+1], data[p+2]) > 150) { torsoX += px; torsoPixels++; }
    }
    const center = torsoPixels ? torsoX / torsoPixels : (left+right)/2;
    const scale = Math.min(size*.86/(bottom-top), size*.473/Math.max(center-left, right-center));
    const key = canvas(size), keyCtx = key.getContext('2d');
    keyCtx.imageSmoothingQuality = 'high';
    keyCtx.drawImage(tile, left, top, right-left, bottom-top, size/2+(left-center)*scale, size*.9414-(bottom-top)*scale, (right-left)*scale, (bottom-top)*scale);
    keyframes.push(key); bounds.push({left,top,right,bottom,center,scale});
  }
  // Short dissolves between neighboring keyframes soften small ImageGen pose steps.
  const frames = [], durations = [], tweenCount = 4;
  for (let i = 0; i < keyframes.length; i++) for (let step = 0; step < tweenCount; step++) {
    const progress = step/tweenCount, frame = canvas(size), ctx = frame.getContext('2d');
    const phase = (i+progress)/keyframes.length*Math.PI*2;
    ctx.translate(size/2, size/2 + Math.sin(phase)*1.2); ctx.rotate(Math.sin(phase)*.006); ctx.translate(-size/2, -size/2);
    ctx.globalAlpha = 1-progress; ctx.drawImage(keyframes[i], 0, 0);
    ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = progress; ctx.drawImage(keyframes[(i+1)%keyframes.length], 0, 0);
    frames.push(frame.toDataURL('image/png')); durations.push(65);
  }
  const sheet = canvas(size*4, size*3), sheetCtx = sheet.getContext('2d');
  sheetCtx.fillStyle = '#172118'; sheetCtx.fillRect(0,0,sheet.width,sheet.height);
  keyframes.forEach((key,i) => sheetCtx.drawImage(key, i%4*size, Math.floor(i/4)*size));
  return {frames, durations, keys:keyframes.map(c=>c.toDataURL('image/png')), contactSheet:sheet.toDataURL('image/png'), metrics:{sourceWidth:image.width,sourceHeight:image.height,size,bounds}};
}
