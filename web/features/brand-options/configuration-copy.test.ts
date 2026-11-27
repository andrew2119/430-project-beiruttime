import { describe,it,expect } from 'vitest';
import { configurationField } from './configuration-copy';
describe('configuration field recovery copy',()=>{
 it('keeps missing and stale corrections precise in both languages',()=>{
  expect(configurationField('en','movement','missing')).toContain('Movement: Choose');
  expect(configurationField('en','color','stale_option')).toContain('Option changed');
  expect(configurationField('ar','movement','missing')).toContain('الحركة');
  expect(configurationField('ar','color','stale_option')).toContain('النسخة الحالية');
 });
 it('never renders an unknown upstream field or payload as copy',()=>{
  const value=configurationField('en','private_evidence','private secret');
  expect(value).toBe('Choices: Review the current selection');
  expect(value).not.toContain('private');
 });
});
