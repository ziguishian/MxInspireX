import { describe, expect, it } from 'vitest';
import { htmlPreviewDocument, htmlPreviewSize, resolveHtmlAssets, HTML_PREVIEW_SCALE, HTML_PREVIEW_SANDBOX, HTML_PREVIEW_CSP } from './htmlPreview';
import { boardChanges, cleanBoard } from './canvasEditing';
import { runInNewContext } from 'node:vm';

describe('HTML canvas boundary', () => {
  it('keeps fragment links inside srcdoc without navigating back into the host app', () => {
    const listeners: Record<string, (event: any) => void> = {};
    let scrolled = false, prevented = false;
    const target = {scrollIntoView: () => { scrolled = true; }};
    const document = {getElementById: (id: string) => id === '香型' ? target : null, getElementsByName: () => [], documentElement: target};
    const script = htmlPreviewDocument('<a href="#香型">了解香型</a>').match(/<script>([\s\S]*?)<\/script>/)![1];
    runInNewContext(script, {addEventListener: (name: string, fn: (event: any) => void) => { listeners[name] = fn; }, document});
    const click = (href: string) => listeners.click({button:0, defaultPrevented:false,
      target:{closest:() => ({getAttribute:() => href})}, preventDefault:() => {prevented = true;}});
    click('#%E9%A6%99%E5%9E%8B');
    expect([prevented,scrolled]).toEqual([true,true]);
    prevented = scrolled = false;
    click('https://example.com');
    expect([prevented,scrolled]).toEqual([false,false]);
    click('#missing');
    expect([prevented,scrolled]).toEqual([true,false]);
  });
  it('starts with a desktop viewport and changes layout only through explicit node sizing', () => {
    expect(htmlPreviewSize().width / HTML_PREVIEW_SCALE).toBe(1440);
    expect(htmlPreviewSize({width:400}).width / HTML_PREVIEW_SCALE).toBe(600);
    expect(htmlPreviewSize({width:NaN,height:Infinity})).toEqual({width:960,height:640});
    expect(htmlPreviewSize({width:1,height:9000})).toEqual({width:320,height:1440});
  });
  it('embeds approved local raster references without opening API or external access', () => {
    const source = '<img src="asset://selected"><style>div{background:url(asset://selected)}</style>';
    expect(resolveHtmlAssets(source,{selected:'data:image/png;base64,YQ=='}).match(/data:image\/png/g)).toHaveLength(2);
    expect(resolveHtmlAssets(source,{selected:'https://external.test/image.png'})).toBe(source);
    expect(resolveHtmlAssets(source,{selected:'data:image/svg+xml;base64,YQ=='})).toBe(source);
    expect(htmlPreviewDocument(source,{selected:'data:image/png;base64,YQ=='})).not.toContain('asset://selected');
  });
  it('isolates preview code and places the restrictive policy before generated markup', () => {
    const markup = '<html><script>fetch("http://127.0.0.1:8765/api/projects")</script><h1>Preview</h1></html>';
    const document = htmlPreviewDocument(markup);
    expect(HTML_PREVIEW_SANDBOX.split(' ')).toEqual(['allow-scripts']);
    expect(document.indexOf('Content-Security-Policy')).toBeLessThan(document.indexOf('<script>'));
    expect(HTML_PREVIEW_CSP).toContain("connect-src 'none'");
    expect(HTML_PREVIEW_CSP).toContain("form-action 'none'");
    expect(HTML_PREVIEW_CSP).toContain("frame-src 'none'");
    expect(HTML_PREVIEW_CSP).not.toContain('https:');
  });
  it('persists authored HTML across canvas edits without renderer context', () => {
    const before = { nodes: [{id:'page',position:{x:10,y:20},data:{kind:'html',html:'<h1>Old</h1>',apiBaseUrl:'local'}}], edges:[] };
    const after = cleanBoard(before);
    after.nodes[0].data.html = '<button>New</button>';
    expect(after.nodes[0].data.apiBaseUrl).toBeUndefined();
    expect(boardChanges(before,after).upsertNodes[0].data.html).toBe('<button>New</button>');
  });
});
