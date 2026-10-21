import type { Project } from '../../../../../packages/contracts/project';

export type DesignExampleSlide = { title: string; alt: string; prompt: string };
export type DesignExample = {
  id: string; category: string; title: string; projectSlug?: string; demoId?: string; requiresImport?: boolean;
  cover: string;
  slides: readonly DesignExampleSlide[];
};

const productCover = (name: string) => `${import.meta.env.BASE_URL}assets/showcase-products/${name}`;

export const readyShowcaseSlugs = (projects: readonly Pick<Project, 'slug' | 'brief' | 'previewRevision'>[]): string[] => projects
  .filter(project => project.brief?.startsWith('已保存的演示案例：') && project.previewRevision && project.previewRevision !== 'empty')
  .map(project => project.slug);

// Curated projects placed on the home page. projectSlug opens the real local
// project; demoId remains available for explicitly requested product demos.
export const designExamples: readonly DesignExample[] = [
  {
    id: 'ci', category: '青瓷器物', title: '瓷 · 德寿宫', projectSlug: 'showcase-ci', requiresImport: true,
    cover: productCover('ci-cover-calligraphy.png'),
    slides: [{ title: '青瓷葫芦礼', alt: '青瓷葫芦罐与书法瓷字、竖排德寿宫的青绿封面', prompt: '打开瓷：德寿宫青瓷葫芦礼项目。' }],
  },
  {
    id: 'shan-ming', category: '高山茶品牌', title: '山茗', projectSlug: 'showcase-shan-ming', requiresImport: true,
    cover: productCover('shan-ming-cover.png'),
    slides: [{ title: '高山茶包装系统', alt: '山茗茶礼盒、茶盒与纸杯组成的品牌视觉全景', prompt: '打开山茗高山茶品牌包装项目。' }],
  },
  {
    id: 'ce-ma', category: '青瓷挂件', title: '策马寻路', projectSlug: 'showcase-ce-ma', requiresImport: true,
    cover: productCover('ce-ma-cover.png'),
    slides: [{ title: '东方青瓷挂件系列', alt: '策马寻路书法题字与青瓷马形挂件的暖白封面', prompt: '打开策马寻路东方青瓷挂件项目。' }],
  },
  {
    id: 'jin', category: '织锦饰品', title: '锦 · 宋锦葫芦', projectSlug: 'showcase-jin', requiresImport: true,
    cover: productCover('jin-cover.jpg'),
    slides: [{ title: '织纹与礼赠', alt: '宋锦葫芦饰品在木枝上的六款实拍陈列', prompt: '打开锦：宋锦葫芦饰品项目。' }],
  },
  {
    id: 'ma-ti', category: '陶瓷文创', title: '马踏平安', projectSlug: 'showcase-ma-ti', requiresImport: true,
    cover: productCover('ma-ti-cover.png'),
    slides: [{ title: '陶瓷随行礼', alt: '马形陶瓷挂饰与节令礼物实拍', prompt: '打开马踏平安陶瓷随行礼项目。' }],
  },
];
