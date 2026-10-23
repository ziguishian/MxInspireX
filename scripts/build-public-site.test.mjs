import { describe, it, expect } from 'vitest';
import { publicSiteFiles } from './build-public-site.mjs';
describe('public product discovery', () => {
  it('does not invent a public URL or index a local preview', () => {
    const files = publicSiteFiles();
    expect(files['index.html']).toContain('noindex,nofollow');
    expect(files['index.html']).not.toContain('rel="canonical"');
    expect(files['sitemap.xml']).toBeUndefined();
    expect(files['index.html']).toContain('不是。项目与文件保存在本机');
  });
  it('provides static content, canonical, truthful schema and matching sitemap', () => {
    const files = publicSiteFiles('https://example.com/MxInspireX/');
    expect(files['index.html']).toContain('href="https://example.com/MxInspireX/"');
    expect(files['sitemap.xml']).toContain('<loc>https://example.com/MxInspireX/</loc>');
    expect(files['robots.txt']).toContain('Sitemap: https://example.com/MxInspireX/sitemap.xml');
    const schema = JSON.parse(files['index.html'].match(/application\/ld\+json">(.*?)<\/script>/s)[1]);
    expect(schema.name).toBe('MxinspireX');
    expect(schema.aggregateRating).toBeUndefined();
    expect(schema.offers).toBeUndefined();
    expect(files['sitemap.xml']).not.toMatch(/projects|settings|references/);
  });
  it.each(['http://localhost:5173', 'https://user:pass@example.com', 'https://example.com/?secret=x'])('rejects unsafe site URL %s', url => {
    expect(() => publicSiteFiles(url)).toThrow();
  });
});
