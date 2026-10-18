MATCH (:System {name:$system})<-[:MENTIONS]-(src:Source)-[:AUTHORED_BY]->(p:Person)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
WITH p, t, count(DISTINCT src) AS evidence,
     collect(DISTINCT src.title)[..3] AS via, collect(DISTINCT src.id)[..3] AS via_ids
RETURN p.name AS person, p.role AS role, t.name AS team, p.status AS status, evidence, via, via_ids
ORDER BY evidence DESC, person LIMIT 5
