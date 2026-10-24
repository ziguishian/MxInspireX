const maxInputBytes = 20 * 1024 * 1024;
const maxStoredLength = 1400000;

/** Local background preparation; never uploads the image to a provider. */
export async function prepareCanvasBackgroundImage(file: File): Promise<string> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)
    && !(file.type === '' && /\.(png|jpe?g|webp)$/i.test(file.name))) {
    throw new Error('请选择 PNG、JPEG 或 WebP 图片。');
  }
  if (file.size > maxInputBytes) throw new Error('图片超过 20 MB，请选择较小的图片。');
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); }
  catch { throw new Error('图片无法解码，请更换 PNG、JPEG 或 WebP 文件。'); }
  try {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法处理背景图片，请重新打开应用后再试。');
    let scale = Math.min(1, 2560 / Math.max(bitmap.width, bitmap.height));
    for (let attempt = 0; attempt < 5; attempt++) {
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL('image/webp', 0.85);
      if (data.startsWith('data:image/') && data.length <= maxStoredLength) return data;
      scale *= 0.7;
    }
    throw new Error('图片内容过大，无法保存为画布背景，请换用较小的图片。');
  } finally { bitmap.close(); }
}
