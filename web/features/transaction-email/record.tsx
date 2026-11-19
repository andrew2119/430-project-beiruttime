import { Badge, Button, Card } from '@beirut-time/ui/foundation';
import type { EmailRecord } from '@contracts/contracts-comms/transaction-email';
import { copy } from './copy';

export function RecordCard({record, locale, opening, open}: {record:EmailRecord; locale:'en'|'ar'; opening:boolean; open:()=>void}) {
  const t = copy[locale];
  return <Card><article className="transaction-email-record">
    <Badge>{t.synthetic}</Badge><h2 className="bt-heading">{t[record.kind]}</h2><p className="bt-text" role="status">{t[record.state]}</p>
    <p className="bt-text"><bdi dir="ltr">{record.operation_id}</bdi></p>
    <p className="bt-text">{t.available}: <time dateTime={record.available_at}>{new Date(record.available_at).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time></p>
    {record.next_review_at && <p className="bt-text">{t.support}: <time dateTime={record.next_review_at}>{new Date(record.next_review_at).toLocaleString(locale,{timeZone:'Asia/Beirut'})}</time></p>}
    <Button busy={opening} onClick={open}>{t.open}</Button>
  </article></Card>;
}
