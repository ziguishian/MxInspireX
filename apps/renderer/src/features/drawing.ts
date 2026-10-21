export type DrawingStroke = { tool: 'pen' | 'eraser'; color: string; width: number; points: [number, number][] };
export type DrawingContent = { width: number; height: number; strokes: DrawingStroke[] };
export type DrawingDocument = DrawingContent & { revision: string; hasContent: boolean };
export const copyDrawing = (drawing: DrawingContent): DrawingContent => JSON.parse(JSON.stringify({ width: drawing.width, height: drawing.height, strokes: drawing.strokes }));

export function drawingPoint(clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number }, drawing: DrawingContent): [number, number] {
  return [Math.round(Math.max(0, Math.min(drawing.width, (clientX - rect.left) / rect.width * drawing.width)) * 10) / 10,
    Math.round(Math.max(0, Math.min(drawing.height, (clientY - rect.top) / rect.height * drawing.height)) * 10) / 10];
}

export function paintDrawing(canvas: HTMLCanvasElement, drawing: DrawingContent) {
  if (canvas.width !== drawing.width) canvas.width = drawing.width;
  if (canvas.height !== drawing.height) canvas.height = drawing.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  for (const stroke of drawing.strokes) {
    const first = stroke.points[0]; if (!first) continue;
    ctx.strokeStyle = ctx.fillStyle = stroke.tool === 'eraser' ? '#ffffff' : stroke.color;
    ctx.lineWidth = stroke.width;
    ctx.beginPath(); ctx.arc(first[0], first[1], stroke.width / 2, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.moveTo(...first);
    for (const point of stroke.points.slice(1)) ctx.lineTo(...point);
    ctx.stroke();
  }
}
