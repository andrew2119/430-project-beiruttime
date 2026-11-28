import { expect, it } from 'vitest';
import { retainCommand } from '../../../../web/features/repair-quotes/pending';

it('retains timeout payload and reference across pagination and expiry refresh',()=>{
 const workspace=new Map<string,{action:string;body:{selected_line_ids:string[];quote_revision:number};key:string;error?:Error}>();
 const original=retainCommand(workspace,'quote',()=>({action:'accept',body:{selected_line_ids:['mandatory','optional'],quote_revision:1},key:'repair-once'}));
 original.error=new Error('timeout');
 // Leaving the page discards card state, while the workspace keeps the command.
 const another=retainCommand(workspace,'another',()=>({action:'decline',body:{selected_line_ids:[],quote_revision:1},key:'another-once'}));
 expect(another.key).toBe('another-once');
 const retry=retainCommand(workspace,'quote',()=>({action:'decline',body:{selected_line_ids:[],quote_revision:2},key:'replacement'}));
 expect(retry).toBe(original);
 expect(JSON.stringify([retry.action,retry.body,retry.key])).toBe(JSON.stringify([original.action,original.body,'repair-once']));
 expect(retry.error?.message).toBe('timeout');
 workspace.delete('quote');
 expect(retainCommand(workspace,'quote',()=>({...original,key:'new-conclusive-action'})).key).toBe('new-conclusive-action');
});

it('retains unsent choices and acknowledgements across page-away and page-back',()=>{
 const drafts=new Map<string,{selected:string[];assessmentAccepted:boolean;returnAccepted:boolean;consent:boolean}>();
 const mount=(scope:string,revision:number)=>retainCommand(drafts,`${scope}:quote:${revision}`,()=>({selected:['mandatory'],assessmentAccepted:false,returnAccepted:false,consent:false}));
 const first=mount('personal',1);
 Object.assign(first,{selected:['mandatory','optional'],assessmentAccepted:true,returnAccepted:true,consent:true});
 retainCommand(drafts,'personal:another:1',()=>({selected:[],assessmentAccepted:false,returnAccepted:false,consent:false}));
 expect(mount('personal',1)).toEqual(first);
 expect(mount('personal',1).selected).toEqual(['mandatory','optional']);
 expect(mount('personal',2).consent).toBe(false);
 expect(mount('business',1).assessmentAccepted).toBe(false);
 const nextIdentity=new Map();
 expect(nextIdentity.size).toBe(0);
});
