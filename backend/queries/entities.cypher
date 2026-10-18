MATCH (n)
WHERE n:System OR n:Person OR n:Project OR n:Decision
OPTIONAL MATCH (n)-[:ABOUT]->(s:System)
RETURN labels(n)[0] AS kind, coalesce(n.name, n.id) AS name, n.status AS status,
       n.summary AS summary, s.name AS about
ORDER BY kind, name
