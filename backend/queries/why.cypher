MATCH (:System {name:$system})<-[:ABOUT]-(d:Decision {status:'active'})
MATCH p = (d)-[:SUPERSEDES*0..5]->(old:Decision)
MATCH (old)-[:RECORDED_IN]->(src:Source)
OPTIONAL MATCH (old)-[:MADE_BY]->(who:Person)
RETURN d.id AS head, length(p) AS step, old.id AS id, old.summary AS decision,
       old.at AS at, old.status AS status, src.id AS source_id, src.kind AS kind,
       src.title AS source, who.name AS by
ORDER BY head, step
