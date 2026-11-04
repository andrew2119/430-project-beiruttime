'use client';
import Link from 'next/link';
import { BidiReference, Button, Card } from '@beirut-time/ui';
import { type Queue } from './api';
import { FeatureFrame, LoadState, useCopy, useResource } from './common';

export default function DashboardScreen({token,queueId}:{token:string;queueId?:string}) {
  const {locale,t}=useCopy();
  const result=useResource<{queues:Queue[]}|Queue>(token,'communications',queueId?`operator-workspace/queues/${queueId}`:'operator-workspace/queues');
  const queues=result.data?('queues' in result.data?result.data.queues:[result.data]):[];
  return <FeatureFrame title="dashboard" intro="dashboardIntro"><div className="ops-toolbar"><Button type="button" className="button-secondary" onClick={result.refresh}>{t('refresh')}</Button></div><LoadState loading={result.loading} error={result.error} refresh={result.refresh}/><div className="ops-queue-grid">{queues.map(queue=><Card key={queue.id}><div className="ops-card-heading"><h2>{t(queue.id)}</h2><span className="ops-badge">{t(queue.state)}</span></div>{queue.state==='awaiting_prerequisite'&&<><p>{t('prerequisites')}</p><p className="ops-muted">{t('commandsUnavailable')}</p></>}{queue.state==='empty'&&<p>{t('emptyBody')}</p>}{queue.state==='denied'&&<p>{t('deniedBody')}</p>}{queue.state==='unavailable'&&<p>{t('unavailableBody')}</p>}
    <ul className="ops-records">{queue.items.map(item=><li key={item.id}><div><BidiReference>{item.id}</BidiReference><p>{t(item.status)} · {t('revision')} {new Intl.NumberFormat(locale).format(item.revision)}</p></div></li>)}</ul>
    {queue.state!=='denied'&&<Link className="button button-secondary" href={`/${locale}${queue.route}`}>{t('viewQueue')}</Link>}</Card>)}</div></FeatureFrame>;
}
