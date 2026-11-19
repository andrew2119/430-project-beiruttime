import { vi } from 'vitest';
// A minimal native host exercises mounted reconciliation; geometry needs a browser.
export class Element extends EventTarget {
 nodeType=1; nodeName:string; tagName:string; namespaceURI='http://www.w3.org/1999/xhtml';
 children:Element[]=[]; parentNode:Element|null=null; attributes=new Map<string,string>();
 style={}; dataset:Record<string,string>={}; clientWidth=0; ownerDocument:DocumentHost; textContent='';
 constructor(name:string,doc:DocumentHost) {super();this.nodeName=this.tagName=name.toUpperCase();this.ownerDocument=doc;}
 appendChild(child:Element) {if(child.parentNode) child.parentNode.removeChild(child);this.children.push(child);child.parentNode=this;return child;}
 removeChild(child:Element) {this.children.splice(this.children.indexOf(child),1);child.parentNode=null;return child;}
 insertBefore(child:Element,before:Element) {if(child.parentNode) child.parentNode.removeChild(child);this.children.splice(this.children.indexOf(before),0,child);child.parentNode=this;return child;}
 setAttribute(name:string,value:string) {this.attributes.set(name,String(value));}
 removeAttribute(name:string) {this.attributes.delete(name);}
 matches(selector:string):boolean {
  if(selector.startsWith('.')) return (this.attributes.get('class')??'').split(/\s+/).includes(selector.slice(1));
  return this.tagName===selector.toUpperCase();
 }
 closest(selector:string):Element|null {
  if(this.matches(selector)) return this;
  return this.parentNode?.closest(selector)??null;
 }
 focus() {this.ownerDocument.activeElement=this;}
 get firstChild() {return this.children[0]??null;}
 get lastChild():Element|null {return this.children.at(-1)??null;}
 get nextSibling():Element|null {return this.parentNode?.children[this.parentNode.children.indexOf(this)+1]??null;}
 contains(node:Element):boolean {return this===node || this.children.some(child=>child.contains(node));}
 buttons():Element[] {return [...(this.tagName==='BUTTON'?[this]:[]),...this.children.flatMap(child=>child.buttons())];}
 click() {
  const props=Object.entries(this).find(([key])=>key.startsWith('__reactProps$'))?.[1] as {onClick?:()=>void}|undefined;
  props?.onClick?.();
 }
}
export class DocumentHost {
 nodeType=9; activeElement:Element|null=null; documentElement=new Element('html',this);
 body=new Element('body',this); defaultView=Object.assign(new EventTarget(),{setTimeout,clearTimeout,HTMLElement:Element,HTMLIFrameElement:class {},location:{href:'https://example.test/en/sellers/seller-1?filter=watch#listings'},history:{replaceState:vi.fn((_data:unknown,_title:string,url:URL)=>{this.defaultView.location.href=String(url);})}});
 createElement(name:string) {return new Element(name,this);}
 createElementNS(_namespace:string,name:string) {return this.createElement(name);}
 createTextNode(text:string) {const node=new Element('#text',this);node.nodeType=3;node.textContent=text;return node;}
 addEventListener() {} removeEventListener() {}
}
