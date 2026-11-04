// Check owned web features against the frozen provider interface before its branch lands.
// This changes no production import, root config, provider file or dependency manifest.
import { mkdir,writeFile,access } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const root=resolve(fileURLToPath(new URL('../../..',import.meta.url)));
const fixture=process.env.BT_IDENTITY_CONTRACT_FIXTURE;
if(!fixture)throw Error('Set BT_IDENTITY_CONTRACT_FIXTURE to the read-only Identity session contract directory');
await access(resolve(fixture,'session.ts'));await access(resolve(fixture,'index.ts'));
await mkdir(resolve(root,'node_modules/l08'),{recursive:true});
const path=resolve(root,'node_modules/l08/tsconfig.json');
await writeFile(path,JSON.stringify({extends:resolve(root,'web/tsconfig.json'),compilerOptions:{incremental:false,paths:{'@/*':[resolve(root,'web/*')],'@contracts/*':[resolve(root,'packages/*')],'@/features/identity/session':[resolve(root,'tests/lanes/L08/identity-session.d.ts')],'@contracts/contracts-identity/accounts':[resolve(fixture,'index.ts')]}},include:[resolve(root,'web/**/*.ts'),resolve(root,'web/**/*.tsx')],exclude:[resolve(root,'web/node_modules')]}));
const result=spawnSync(resolve(root,'web/node_modules/.bin/tsc'),['--noEmit','-p',path],{stdio:'inherit'});
process.exit(result.status??1);
