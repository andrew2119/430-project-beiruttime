'use client';
import { RefreshCw } from 'lucide-react';
import { AnimatedList, BidiReference, ButtonLink, Card, StatusBadge } from '@beirut-time/ui';
import { type Queue } from './api';
import { FeatureFrame, LoadState, useCopy, useResource } from './common';

export default function DashboardScreen({token,queueId}:{token:string;queueId?:string}) {
  const {locale,t}=useCopy();
  const result=useResource<{queues:Queue[]}|Queue>(token,'communications',queueId?`operator-workspace/queues/${queueId}`:'operator-workspace/queues');
  const queues=result.data?('queues' in result.data?result.data.queues:[result.data]):[];
  return <FeatureFrame title="dashboard" intro="dashboardIntro" actions={[{id:'refresh',label:t('refresh'),icon:RefreshCw,busy:result.loading,onSelect:result.refresh}]}><LoadState loading={result.loading} error={result.error} empty={!result.loading&&!result.error&&queues.length===0} refresh={result.refresh}/><AnimatedList items={queues} getKey={queue=>queue.id} grid className="ops-queue-grid">{queue=><Card key={queue.id}><div className="ops-card-heading"><h2>{t(queue.id)}</h2><StatusBadge hue={queue.state==='ready'?'green':queue.state==='awaiting_prerequisite'?'orange':'neutral'}>{t(queue.state)}</StatusBadge></div>{queue.state==='awaiting_prerequisite'&&<><p>{t('prerequisites')}</p><p className="ops-muted">{t('commandsUnavailable')}</p></>}{queue.state==='empty'&&<p>{t('emptyBody')}</p>}{queue.state==='denied'&&<p>{t('deniedBody')}</p>}{queue.state==='unavailable'&&<p>{t('unavailableBody')}</p>}
    <ul className="ops-records">{queue.items.map(item=><li key={item.id}><div><BidiReference>{item.id}</BidiReference><p>{t(item.status)} · {t('revision')} {new Intl.NumberFormat(locale).format(item.revision)}</p></div></li>)}</ul>
    {queue.state!=='denied'&&<ButtonLink variant="outline" href={`/${locale}${queue.route}`}>{t('viewQueue')}</ButtonLink>}</Card>}</AnimatedList></FeatureFrame>;
}
