'use client';

import { useState } from 'react';
import { Button, ButtonLink, Card, Input, Segmented, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { copy } from './copy';
import { helpMatches, policyGuidance } from './model';
import './styles.css';

const commercialSections = new Set(['fees','jobs','payments','failed-inspection','returns','warranty']);
export default function HelpPolicies() {
  const locale = useLocale(), t = copy[locale];
  const [query,setQuery] = useState(''), [section,setSection] = useState('all');
  const articles = helpMatches(query).filter(article=>section === 'all' || commercialSections.has(article.id));
  return <PageFrame>
    <PageHeader title={t.title} lead={t.intro} count={<>{t.version}: <bdi>{policyGuidance.revision}</bdi></>}
      tools={<div className="l20-help-search"><Input label={t.search} id="help-search" type="search" value={query} onValueChange={value=>setQuery(value.slice(0,200))}/><Button variant="outline" onClick={()=>setQuery('')}>{t.clear}</Button></div>}
      tabs={<Segmented label={t.mode} value={section} onValueChange={setSection} locale={locale} options={[{value:'all',label:t.all},{value:'commercial',label:t.commercial}]}/>}/>
    <PageBody>
      <p className="bt-text" role="status">{t.result}: <span className="bt-number">{formatNumber(articles.length,locale)}</span></p>
      {articles.length === 0 && <State title={t.empty} body={t.emptyBody}/>}
      <div className="l20-help-articles">{articles.map(article=><Card key={article.id}><article aria-labelledby={`help-${article.id}`}><h2 id={`help-${article.id}`} className="bt-heading">{article[locale].title}</h2><p className="bt-text l20-help-copy">{article[locale].body}</p></article></Card>)}</div>
      <section aria-label={t.support}><State title={t.unavailable} body={t.contact}><ButtonLink href={`/${locale}/account?next=%2Fhelp`}>{t.recovery}</ButtonLink></State></section>
      <section aria-label={t.terms}><State title={t.terms} body={t.termsBody}/></section>
    </PageBody>
  </PageFrame>;
}
