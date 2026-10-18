MATCH (d:Decision)-[:ABOUT]->(:System {name:$system})
WHERE d.at <= $date AND (d.superseded_at IS NULL OR d.superseded_at > $date)
OPTIONAL MATCH (d)-[:RECORDED_IN]->(src:Source)
RETURN d.id AS id, d.summary AS believed, d.at AS since, d.status AS status,
       src.id AS source_id, src.title AS source
ORDER BY since DESC
