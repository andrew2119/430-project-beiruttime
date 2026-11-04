'use client';
import { useQuery } from '@tanstack/react-query';
import { request } from '@/lib/api/client';
import type { StatusResponse } from '@/lib/api/types';
import type { Locale, Messages } from '@/lib/i18n';
import { Button } from './primitives';
const labels: Record<string, [string,string]> = { identity:['Identity','الهوية'], catalog:['Catalog','الكتالوج'], auction:['Auctions','المزادات'], pricing:['Pricing','التسعير'], orders:['Orders','الطلبات'], eligibility:['Eligibility','الأهلية'], trust:['Trust','الثقة'], communications:['Communications','التواصل'], 'service-operations':['Watch care','العناية بالساعات'] };
export function ServiceStatus({ locale, t }: { locale: Locale; t: Messages }) {
  const query = useQuery({ queryKey: ['public','service-status'], queryFn: ({ signal }) => request<StatusResponse>('/api/web/v1/status', { signal }), refetchInterval: 30000 });
  return <section id="marketplace-status" className="status-section" aria-labelledby="status-title"><div className="section-heading"><div><p className="eyebrow">BEIRUT TIME</p><h2 id="status-title">{t.platform}</h2><p>{t.platformBody}</p></div></div>
    {query.isPending ? <p role="status">{t.checking}</p> : query.isError ? <div className="notice" role="status"><p>{t.unavailable}</p><Button onClick={() => query.refetch()}>{t.retry}</Button></div> : <ul className="service-grid">{query.data.services.map(service => <li key={service.service}><span className={`status-dot ${service.status}`} aria-hidden="true"/><span>{labels[service.service]?.[locale === 'en' ? 0 : 1] ?? service.service}</span><small>{service.status === 'ready' ? t.ready : t.unavailable}</small></li>)}</ul>}
  </section>;
}
