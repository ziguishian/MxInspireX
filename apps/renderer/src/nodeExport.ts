import { HTML_PREVIEW_SCALE, htmlPreviewDocument, resolveHtmlAssets } from './htmlPreview';
import { canvasNodeKind, nodePreviewSize } from './nodeSizing';

export type NodeExportFormat = 'original' | 'html' | 'pdf';
type NodeData = Record<string, any>;

export function nodeMediaUrl(data: NodeData): string {
  if (data.localFile) return data.localFile;
  const id = data.kind === 'cad' ? data.previewAssetId || data.cad?.files?.glb : data.assetId || data.asset?.id;
  return id ? `${data.apiBaseUrl}/api/projects/${encodeURIComponent(data.asset?.projectId || data.projectId)}/assets/${encodeURIComponent(id)}/content` : '';
}

export function canExportNode(data: NodeData): boolean {
  if (data.generating || data.uploading || data.error) return false;
  return Boolean(nodeMediaUrl(data) || (canvasNodeKind(data) === 'html' ? data.html : data.text || data.summary));
}

export function nodeSaveLabel(data: NodeData): string {
  if (data.asset?.mime === 'image/svg+xml' || data.vectorSource) return '下载矢量 SVG';
  return ({ image: '保存图像', video: '保存视频', audio: '保存音频', text: data.downloadable ? '保存文件' : '保存文本', '3d': '保存 3D 模型', cad: '导出 CAD 文件组' } as Record<string, string>)[canvasNodeKind(data)] || '保存素材';
}

export function exportFilename(data: NodeData, extension: string): string {
  let name = String(data.title || data.label || data.asset?.pathRelative?.split(/[\\/]/).pop() || '设计素材')
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').replace(/[. ]+$/g, '').trim() || '设计素材';
  if (canvasNodeKind(data) === 'html') name = name.replace(/\.html?$/i, '') || '网页';
  return extension && !name.toLowerCase().endsWith(`.${extension.toLowerCase()}`) ? `${name}.${extension}` : name;
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

async function originalBlob(data: NodeData): Promise<Blob> {
  let response: Response;
  try {
    // Preview images may already have been cached without CORS headers by an
    // older sidecar. Read the original bytes afresh when explicitly saving.
    response = await fetch(nodeMediaUrl(data), { cache: 'no-store' });
  } catch {
    throw new Error('素材下载连接失败，请刷新页面后重试。');
  }
  if (response.status === 404) throw new Error('素材文件不存在或已被移除，无法保存。');
  if (!response.ok) throw new Error('素材文件读取失败，请重试。');
  return response.blob();
}

// Browsers use their native print dialog's “Save as PDF” destination. Keep the
// document isolated, just like the canvas preview, while allowing this dialog.
function printHtmlInBrowser(html: string, title: string, width: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const frame = document.createElement('iframe');
    frame.title = title;
    frame.setAttribute('sandbox', 'allow-scripts allow-modals');
    frame.style.cssText = `position:fixed;left:-10000px;top:0;width:${width}px;height:1000px;border:0;`;
    const token = crypto.randomUUID();
    const cleanup = () => { clearTimeout(timer); window.removeEventListener('message', receive); frame.remove(); };
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow || event.data?.token !== token) return;
      if (event.data.type === 'printed') { cleanup(); resolve(); }
      if (event.data.type === 'error') { cleanup(); reject(new Error('网页打印失败，请重试。')); }
    };
    const timer = window.setTimeout(() => { cleanup(); reject(new Error('网页打印超时，请重试。')); }, 300_000);
    window.addEventListener('message', receive);
    const bridge = `<script>addEventListener('load', async () => {
      try {
        document.title = ${JSON.stringify(title).replace(/</g, '\\u003c')};
        for (const image of document.images) image.loading = 'eager';
        await Promise.all([document.fonts.ready, ...Array.from(document.images, image => image.decode().catch(() => {}))]);
        addEventListener('afterprint', () => parent.postMessage({token:${JSON.stringify(token)},type:'printed'}, '*'), {once:true});
        focus(); print();
      } catch { parent.postMessage({token:${JSON.stringify(token)},type:'error'}, '*'); }
    }, {once:true});<\/script>`;
    frame.srcdoc = htmlPreviewDocument(bridge + '<style>html{-webkit-print-color-adjust:exact;print-color-adjust:exact}</style>' + html);
    document.body.append(frame);
  });
}

export async function exportNode(data: NodeData, format: NodeExportFormat = 'original'): Promise<void> {
  if (!canExportNode(data)) throw new Error('素材尚未生成完成，暂时无法保存。');
  const kind = canvasNodeKind(data);
  if (kind === 'cad') {
    const url = `${data.apiBaseUrl}/api/projects/${encodeURIComponent(data.projectId || data.asset?.projectId)}/cad/models/${encodeURIComponent(data.assetId || data.asset.id)}/export`;
    const response = await fetch(url); if (!response.ok) throw new Error('CAD 文件组导出失败');
    saveBlob(await response.blob(), exportFilename(data, 'zip')); return;
  }
  if (kind === 'html') {
    const source = data.html || await (await originalBlob(data)).text();
    const html = resolveHtmlAssets(source, data.htmlAssets);
    if (format === 'pdf') {
      const width = Math.round(nodePreviewSize(data).width / HTML_PREVIEW_SCALE);
      if (window.studio?.exportHtmlPdf) {
        const bytes = await window.studio.exportHtmlPdf({ html, width });
        saveBlob(new Blob([new Uint8Array(bytes)], { type: 'application/pdf' }), exportFilename(data, 'pdf'));
      } else {
        await printHtmlInBrowser(html, exportFilename(data, 'pdf'), width);
      }
    } else {
      saveBlob(new Blob([html], { type: 'text/html;charset=utf-8' }), exportFilename(data, 'html'));
    }
    return;
  }
  if (format !== 'original') throw new Error('只有网页支持此导出格式。');
  if (nodeMediaUrl(data)) {
    const blob = await originalBlob(data);
    const extension = /\.([a-z0-9]+)$/i.exec(data.asset?.pathRelative || '')?.[1]
      || ({ 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif', 'video/mp4': 'mp4', 'video/webm': 'webm', 'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'application/pdf': 'pdf' } as Record<string, string>)[blob.type.split(';')[0]] || '';
    saveBlob(blob, exportFilename(data, extension));
  } else {
    saveBlob(new Blob([data.text || data.summary || ''], { type: 'text/plain;charset=utf-8' }), exportFilename(data, 'txt'));
  }
}
