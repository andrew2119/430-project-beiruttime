import path from 'node:path';
export default {agentRules:false,experimental:{cpus:1},webpack(config: {resolve:{alias:Record<string,string>;modules?:string[]}}){
  config.resolve.modules=[path.resolve(process.cwd(),'../../../../web/node_modules'),...(config.resolve.modules??[])];
  config.resolve.alias['@/registry-loader']=path.resolve(process.cwd(),'registry.ts');
  config.resolve.alias['@/features/identity/session']=path.resolve(process.cwd(),'../fixtures/session-runtime.ts');
  return config;
}};
