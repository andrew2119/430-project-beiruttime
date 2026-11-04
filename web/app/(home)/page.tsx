import { messages } from '@/lib/i18n';
import { getLocale } from '@/shell/locale';
import { hasRoute } from '@/registry-loader';
import { Button, ButtonLink } from '@/shell/primitives';
import { WatchIllustration } from '@/shell/watch-illustration';
import { ServiceStatus } from '@/shell/service-status';
export default async function Storefront() {
  const locale = await getLocale();
  const t = messages(locale);
  return <>
    <section className="hero">
      <div className="hero-copy"><p className="eyebrow">{t.eyebrow}</p><h1>{t.headline}</h1><p className="hero-intro">{t.intro}</p><div className="hero-actions">{hasRoute('/watches') ? <ButtonLink href={`/${locale}/watches`}>{t.discover}<span aria-hidden="true" className="direction-arrow">↗</span></ButtonLink> : <Button disabled title={t.emptyBody}>{t.discover}</Button>}<ButtonLink className="button-secondary" href={`/${locale}/about`}>{t.promise1}</ButtonLink></div><p className="edition">{t.edition}</p></div>
      <figure className="hero-art"><div className="orbital orbital-one"/><div className="orbital orbital-two"/><WatchIllustration label={t.illustration}/><figcaption>{t.illustrationLabel}</figcaption></figure>
    </section>
    <section className="promises" aria-labelledby="promise-title"><div className="section-heading"><p className="eyebrow">{t.tagline}</p><h2 id="promise-title">{t.promiseTitle}</h2></div><div className="promise-grid">{[1,2,3].map((n) => <article key={n}><span className="promise-number" aria-hidden="true">0{n}</span><h3>{t[`promise${n}` as 'promise1']}</h3><p>{t[`promise${n}Body` as 'promise1Body']}</p></article>)}</div></section>
    <ServiceStatus locale={locale} t={t}/>
  </>;
}
