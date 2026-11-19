CREATE TABLE IF NOT EXISTS l22_alert_subscriptions (
  owner TEXT NOT NULL, watch TEXT NOT NULL, kind TEXT NOT NULL,
  since_revision INTEGER NOT NULL, source_revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
  PRIMARY KEY(owner,watch,kind));
INSERT OR IGNORE INTO l22_alert_subscriptions
  SELECT s.owner,s.watch,j.value,s.revision,COALESCE(f.revision,0),COALESCE(f.snapshot,'{}')
  FROM l22_saves s JOIN json_each(s.alerts) j
  LEFT JOIN l22_sources f ON f.watch=s.watch
  WHERE s.saved=1;
