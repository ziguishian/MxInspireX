import { describe, it, expect } from 'vitest';
import { taskReferences } from './taskReferences';

describe('submitted reference scope',()=>{
  const input={projectId:'project',assets:[{id:'image',projectId:'project',nodeId:'placement'},{id:'stale',projectId:'project'}],
    files:[{filename:'one.txt',mime:'text/plain',byteSize:1,result:{pathRelative:'one.txt'}},{filename:'two.png',mime:'image/png',byteSize:2,result:{pathRelative:'two.png'}}],
    documents:[{id:'brief',title:'设计要求',pathRelative:'knowledge/documents/brief.txt'}],
    references:[{key:'file:0',token:'@1',label:'one',kind:'text',badge:'@1'},{key:'file:1',token:'@2',label:'two',kind:'image',badge:'@2'},
      {key:'asset:image',token:'@asset:image',aliases:['@参考图'],label:'参考图',kind:'image',badge:'@'}]};
  it('keeps the selected file number and placement, excludes stale mentions',()=>{
    const result=taskReferences({...input,message:'按 @2 和 @参考图 修改 @node:placement'});
    expect(result.referencedFiles).toHaveLength(1);
    expect(result.referencedFiles[0]).toMatchObject({filename:'two.png',index:2});
    expect(result.referencedAssets.map(a=>a.id)).toEqual(['image']);
    expect(result.referencedNodes).toEqual([{id:'placement',projectId:'project'}]);
  });
  it('passes attachments when no specific file is selected, and preserves missing global references',()=>{
    const result=taskReferences({...input,message:'分析这些附件 @knowledge:brief @knowledge:missing'});
    expect(result.referencedFiles).toHaveLength(4);
    expect(result.referencedFiles[3]).toMatchObject({documentId:'missing',scope:'global'});
    expect(result.referencedAssets).toEqual([]);
  });
  it('leaves image purpose to automatic intent detection',()=>{
    const references=input.references.map(reference=>reference.key==='asset:image'?{...reference,referenceMode:'identity' as const}:reference);
    const result=taskReferences({...input,references,message:'按 @2 和 @参考图 修改'});
    expect(result.referencedFiles[0]).toMatchObject({filename:'two.png'});
    expect(result.referencedAssets[0]).toMatchObject({id:'image'});
    expect(result.referencedFiles[0]).not.toHaveProperty('referenceMode');
    expect(result.referencedAssets[0]).not.toHaveProperty('referenceMode');
  });
});
