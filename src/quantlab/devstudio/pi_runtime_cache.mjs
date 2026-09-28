// A bounded per-call copy of Pi's model catalog. Never copies models.json,
// auth.json or credentials, never changes their location, and never fetches.
import {open, lstat} from 'node:fs/promises';
import {constants} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
const MAX_CATALOG_BYTES = 16 * 1024 * 1024;
const same = (a,b) => a.dev===b.dev && a.ino===b.ino && a.size===b.size && a.mtimeMs===b.mtimeMs && a.ctimeMs===b.ctimeMs;
export async function isolatedModelCatalog(sdk, workingDirectory) {
  // Older SDKs without a public agent directory keep their original contract.
  if (typeof sdk.getAgentDir !== 'function') return {options:{allowModelNetwork:false},receipt:{mode:'sdk_default'}};
  const source=join(sdk.getAgentDir(),'models-store.json');
  const target=join(workingDirectory,'models-store.json');
  let input, content, before, sourceObserved=false;
  try {
    const st=await lstat(source);
    sourceObserved=true;
    if (!st.isFile() || st.isSymbolicLink() || st.size>MAX_CATALOG_BYTES) throw new Error('PI_CATALOG_COPY_UNSAFE');
    input=await open(source,constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    before=await input.stat();
    if (!same(st,before)) throw new Error('PI_CATALOG_SOURCE_CHANGED');
    // Bound the allocation/read, including a concurrently growing file.
    const buffer=Buffer.alloc(Math.min(before.size+1,MAX_CATALOG_BYTES+1));
    let count=0;
    while(count<buffer.length) {
      const {bytesRead}=await input.read(buffer,count,buffer.length-count,count);
      if(!bytesRead)break;
      count+=bytesRead;
    }
    if(count!==before.size || !same(before,await input.stat()) || !same(before,await lstat(source))) throw new Error('PI_CATALOG_SOURCE_CHANGED');
    content=buffer.subarray(0,count);
  } catch(error) {
    if(error.code==='ENOENT' && !sourceObserved) content=Buffer.from('{}');
    else if(String(error.message).startsWith('PI_CATALOG_'))throw error;
    else throw new Error('PI_CATALOG_COPY_FAILED: '+(error.code || 'IO_ERROR'));
  } finally {await input?.close();}
  const output=await open(target,'wx',0o600);
  try{await output.writeFile(content);}finally{await output.close();}
  return {options:{allowModelNetwork:false,modelsStorePath:target},receipt:{mode:'isolated_catalog_copy',
    seeded:before!==undefined,bytes:content.length,sha256:createHash('sha256').update(content).digest('hex')}};
}

export function modelLookupError(runtime, modelName) {
  // Never expose config-validation strings, paths, provider headers or secrets.
  const text=String(runtime.getError?.() || '');
  if(/ENOSPC/.test(text))return 'PI_LOCAL_STORAGE_FULL: Pi model/auth availability refresh failed (ENOSPC); model existence is unknown. No inference or retry was performed.';
  if(text)return 'PI_CATALOG_UNAVAILABLE: Pi reported a local registry/availability error; configured model lookup is not reliable. No inference was performed.';
  return 'Pi model not found: '+modelName;
}
