import { showcaseText } from './showcase-canvas-notes.mjs';
export const compactShowcaseSlugs = ['showcase-ci', 'showcase-shan-ming', 'showcase-ce-ma', 'showcase-jin'];
const LEFT = 540, MEDIA = 480, GAP = 32, START = 588, STEP = 512, SECTION = 72;

export function enrichShowcase(slug, board) {
  if (!compactShowcaseSlugs.includes(slug)) throw new Error('不支持的演示项目。');
  const ordered = [...board.nodes].filter(n => Number.isFinite(n.data?.showcaseOrder)).sort((a,b)=>a.data.showcaseOrder-b.data.showcaseOrder);
  const firstChapter = ordered.find(n => n.data?.showcaseRole === 'chapter');
  return { ...board, nodes: board.nodes.map(node => {
    const d = node.data || {}; let width, height;
    if (d.kind === 'text') {
      width = node.id === firstChapter?.id ? MEDIA : LEFT;
      return { ...node, data: { ...d, text: showcaseText(slug, node.id), previewSize: { width, height: 300 }, textStyle: { ...d.textStyle, fontSize: 15 }, previewSizingVersion: 2, autoPositioned: false, showcaseLayoutEdition: 3 } };
    }
    if (d.kind === 'image') {
      const meta = d.asset?.metadata || {}, output = meta.imageOutput || {};
      const w = output.width || meta.width || d.previewSize?.width;
      const h = output.height || meta.height || d.previewSize?.height;
      if (!(w > 0 && h > 0)) throw new Error(`无法确认图片纵横比：${node.id}`);
      width = MEDIA; height = Math.round(width * h / w);
    } else if (d.kind === 'html') { width = 920; height = 640; }
    else throw new Error(`未知的演示节点：${node.id}`);
    return { ...node, data: { ...d, previewSize: { width, height }, previewSizingVersion: 2, autoPositioned: false, showcaseLayoutEdition: 3 } };
  }) };
}

export function compactLayout(board, textHeights) {
  const nodes = board.nodes.map(n => ({ ...n, position: { ...n.position }, data: { ...n.data } }));
  const ordered = [...nodes].filter(n => Number.isFinite(n.data?.showcaseOrder)).sort((a,b)=>a.data.showcaseOrder-b.data.showcaseOrder);
  const height = node => {
    if (node.data.kind === 'text') {
      const measured = textHeights[node.id];
      if (!Number.isFinite(measured) || measured <= 0) throw new Error(`缺少真实文字测量：${node.id}`);
      // Include rendered heading, generous edge allowance and text-font rounding.
      node.data.previewSize = { ...node.data.previewSize, height: Math.ceil(measured) + 12 };
      return node.data.previewSize.height;
    }
    return node.data.previewSize.height + 36;
  };
  const put = (n, x, y) => { n.position = { x, y: Math.ceil(y) }; return n.position.y + height(n); };
  const intro = ordered.find(n => n.data.showcaseRole === 'intro');
  const chapters = []; let current;
  for (const n of ordered) {
    if (n.data.showcaseRole === 'chapter') { current = { note: n, images: [] }; chapters.push(current); }
    else if (n.data.kind === 'image' && current) current.images.push(n);
  }
  if (!intro || !chapters.length || chapters[0].images.length > 2) throw new Error('开场结构与预期不一致。');
  let y = Math.max(put(intro,0,0),put(chapters[0].note,START,0));
  chapters[0].images.forEach((n,i) => { y = Math.max(y,put(n,START+(i+1)*STEP,0)); });
  y += SECTION;
  for (const section of chapters.slice(1)) {
    const bottom = put(section.note,0,y); const columns = [y,y,y];
    for (const n of section.images) {
      const min = Math.min(...columns); const col = columns.indexOf(min);
      columns[col] = put(n,START+col*STEP,columns[col]) + GAP;
    }
    y = Math.max(bottom, ...columns.map(bottom => bottom > y ? bottom-GAP : bottom)) + SECTION;
  }
  const ending = ordered.filter(n => ['marketing','engineering','handoff'].includes(n.data.showcaseRole));
  const columns = [y,y];
  for (const n of ending) {
    const col = columns[0] <= columns[1] ? 0 : 1;
    columns[col] = put(n,col*(LEFT+GAP),columns[col]) + GAP;
  }
  const html = ordered.find(n => n.data.kind === 'html'); if (!html) throw new Error('缺少最终作品集。');
  const htmlBottom = put(html,2*(LEFT+GAP),y);
  y = Math.max(...columns.map(v=>v-GAP),htmlBottom)+SECTION;
  const references = nodes.filter(n => !Number.isFinite(n.data.showcaseOrder));
  const referenceNote = references.find(n => n.data.kind === 'text');
  const referenceImages = references.filter(n => n.data.kind === 'image');
  if (referenceNote) put(referenceNote,0,y);
  referenceImages.forEach((n,i)=>put(n,START+i*STEP,y));
  return { ...board, nodes };
}

export function validateCompact(board) {
  const boxes = board.nodes.map(n => ({ id:n.id, x:n.position.x, y:n.position.y, width:n.data.previewSize.width, height:n.data.previewSize.height+(n.data.kind==='text'?0:36) }));
  for (let i=0;i<boxes.length;i++) for(let j=i+1;j<boxes.length;j++) {
    const a=boxes[i],b=boxes[j];
    if (!(a.x+a.width+16<=b.x || b.x+b.width+16<=a.x || a.y+a.height+16<=b.y || b.y+b.height+16<=a.y)) throw new Error(`节点安全间距不足：${a.id} / ${b.id}`);
  }
  return { width:Math.max(...boxes.map(b=>b.x+b.width)), height:Math.max(...boxes.map(b=>b.y+b.height)), textCharacters:board.nodes.filter(n=>n.data.kind==='text').reduce((sum,n)=>sum+n.data.text.length,0), nodes:boxes.length };
}
