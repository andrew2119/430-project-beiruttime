'use client';
import { Component, type ReactNode } from 'react';
// Optional sale controls fail locally; the gallery and canonical history remain readable.
export class SlotBoundary extends Component<{children:ReactNode;fallback:string},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  render(){return this.state.failed?<p className="notice">{this.props.fallback}</p>:this.props.children;}
}
