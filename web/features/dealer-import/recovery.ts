export function recovery(status:number|undefined):'clear'|'correct'|'retry' {
 if(status===401||status===403)return 'clear';
 if(status===400||status===409||status===413||status===422)return 'correct';
 return 'retry';
}
