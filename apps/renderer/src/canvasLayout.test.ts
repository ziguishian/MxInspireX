import { describe, expect, it } from 'vitest';
import { alignRects, arrangeRects, nearestOpenPosition, rectsOverlap, snapRect } from './canvasLayout';
const a = { id:'a', x:0, y:0, width:300, height:240 };
const b = { id:'b', x:900, y:400, width:300, height:440 };
describe('canvas layout', () => {
  it('snaps within tolerance to matching edges and exposes guidelines', () => {
    const result = snapRect({ ...b, y:6 }, [a], 8);
    expect(result.y).toBe(0);
    expect(result.guides.some(g => g.axis === 'y' && g.value === 0)).toBe(true);
    expect(snapRect({ ...b, y:60 }, [a], 8).y).toBe(60);
  });
  it('places distant nodes beside each other and wraps using the tallest row', () => {
    expect(arrangeRects([a,b,{...a,id:'c',x:4000}],2)).toEqual([{id:'a',x:0,y:0},{id:'b',x:348,y:0},{id:'c',x:0,y:488}]);
  });
  it('moves a rendered node to an open edge when its content grows after placement', () => {
    const intro = { id: 'intro', x: 0, y: 0, width: 360, height: 980 };
    const visual = { id: 'visual', x: 0, y: 400, width: 720, height: 405 };
    const position = nearestOpenPosition(visual, [intro]);
    const moved = { ...visual, ...position };
    expect(rectsOverlap(moved, intro)).toBe(false);
    expect(position).not.toEqual({ x: visual.x, y: visual.y });
  });
  it('aligns differing node sizes by their actual edges and centers', () => {
    expect(alignRects([a,b],'bottom').map(r=>r.y)).toEqual([600,400]);
    expect(alignRects([a,b],'center-y').map(r=>r.y)).toEqual([300,200]);
  });
  it('evenly distributes the gap between nodes while keeping the endpoints', () => {
    expect(alignRects([a,{...a,id:'c',x:360},b],'distribute-x').map(r=>r.x)).toEqual([0,450,900]);
  });
});
