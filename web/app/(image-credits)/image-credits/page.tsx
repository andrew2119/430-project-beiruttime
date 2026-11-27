import Image from 'next/image';
import { BidiReference, StatusBadge } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { copy } from '@/features/listing-editor/copy';
import manifest from '../../../../demo/images-manifest.json';
import { getLocale } from '@/shell/locale';
export default async function Page() {
  const locale=await getLocale(),t=copy(locale);
  return <PageLayout className="discovery-page"><PageHeader title={t.credits} count={t.creditsIntro} /><div className="discovery-grid">{manifest.assets.map(asset=><article className="discovery-watch-card" key={asset.id}><div className="discovery-credit-image"><Image src={'/demo/watches/'+asset.file} alt={locale==='ar'?asset.alt_ar:asset.alt_en} width={asset.local_dimensions[0]} height={asset.local_dimensions[1]} unoptimized sizes="(max-width:850px) 90vw, 400px"/></div><div className="discovery-card-copy discovery-credit-copy"><div><StatusBadge>{t.demo}</StatusBadge></div><h2><BidiReference>{asset.title}</BidiReference></h2><p><BidiReference>{asset.author}</BidiReference> · <BidiReference>{asset.license}</BidiReference></p><p>{t.changes}</p><div className="discovery-header-links"><a className="discovery-text-link" href={asset.source_url} target="_blank" rel="noreferrer">{t.source} ↗</a><a className="discovery-text-link" href={asset.license_url} target="_blank" rel="noreferrer">{t.license} ↗</a></div></div></article>)}</div></PageLayout>;
}
