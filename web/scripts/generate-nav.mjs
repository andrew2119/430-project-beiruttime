// Registration discovery is independent of lane count; consumers add only their file.
import { readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const repo = resolve(root,'..');
const contracts=[]; const namespaces=new Set();
for (const file of (await readdir(`${repo}/contracts/registrations`)).filter(f=>/^L\d\d\.json$/.test(f)).sort()) {
  const entry=JSON.parse(await readFile(`${repo}/contracts/registrations/${file}`,'utf8'));
  if(entry.version!==1 || `${entry.lane}.json`!==file || !/^L(0[0-9]|1[01])$/.test(entry.lane)) throw new Error('Invalid contract registration');
  for(const contract of entry.contracts??[]) {
    const path=resolve(repo,contract.path);
    if(!path.startsWith(`${repo}/packages${sep}`) || !/^[a-z][a-z0-9.-]*\.v[1-9][0-9]*$/.test(contract.namespace) || namespaces.has(contract.namespace)) throw new Error('Invalid contract namespace/path');
    await stat(path); namespaces.add(contract.namespace);
    for(const fixture of contract.fixtures??[]) { const target=resolve(repo,fixture); if(!target.startsWith(repo+sep)) throw new Error('Invalid fixture path'); JSON.parse(await readFile(target,'utf8')); }
    contracts.push({...contract,lane:entry.lane});
  }
}
await writeFile(`${root}contracts.generated.json`,JSON.stringify(contracts,null,2)+'\n');
const entries = (await readdir(`${root}registrations`)).filter(f => /^L\d\d\.ts$/.test(f)).sort();
await writeFile(`${root}registry.generated.ts`, '// Generated. Add web/registrations/Lxx.ts; never edit this index.\n' +
  entries.map((f,i) => `import lane${i} from './registrations/${f.slice(0,-3)}';`).join('\n') +
  `\nimport type { Registration } from './registry-types';\nexport const registrations: Registration[] = [${entries.map((_,i)=>`lane${i}`).join(',')}];\n`);
