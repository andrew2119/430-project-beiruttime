// Minimal host for mounted component checks; geometry belongs to browser checks.
export class HostNode {
  nodeType = 1;
  nodeName: string;
  tagName: string;
  namespaceURI = "http://www.w3.org/1999/xhtml";
  parentNode: HostNode | null = null;
  childNodes: HostNode[] = [];
  style = {};
  attributes = new Map<string, string>();
  value = "";
  checked = false;
  disabled = false;
  textContent = "";
  constructor(name: string, public ownerDocument: HostDocument) {
    this.nodeName = this.tagName = name.toUpperCase();
  }
  appendChild(child: HostNode) {
    child.parentNode?.removeChild(child);
    this.childNodes.push(child);
    child.parentNode = this;
    return child;
  }
  removeChild(child: HostNode) {
    this.childNodes.splice(this.childNodes.indexOf(child), 1);
    child.parentNode = null;
    return child;
  }
  insertBefore(child: HostNode, before: HostNode) {
    child.parentNode?.removeChild(child);
    this.childNodes.splice(this.childNodes.indexOf(before), 0, child);
    child.parentNode = this;
    return child;
  }
  setAttribute(name: string, value: string) { this.attributes.set(name, String(value)); }
  removeAttribute(name: string) { this.attributes.delete(name); }
  addEventListener() {}
  removeEventListener() {}
}
class HostDocument {
  nodeType = 9;
  documentElement = new HostNode("html", this);
  body = new HostNode("body", this);
  activeElement = this.body;
  defaultView = {HTMLElement: HostNode, HTMLIFrameElement: class {}};
  createElement(name: string) { return new HostNode(name, this); }
  createElementNS(_namespace: string, name: string) { return this.createElement(name); }
  createTextNode(value: string) {
    const node = new HostNode("#text", this);
    node.nodeType = 3;
    node.textContent = value;
    return node;
  }
  addEventListener() {}
  removeEventListener() {}
}
export function mountedHost() {
  const document = new HostDocument();
  return {document, window: document.defaultView, container: document.createElement("div")};
}
export function descendants(node: HostNode): HostNode[] {
  return [node, ...node.childNodes.flatMap(descendants)];
}
