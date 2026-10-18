MATCH (d:Decision)-[:ABOUT]->(s:System)
WHERE toLower(d.summary) CONTAINS toLower($q)
RETURN s.name AS name, d.id AS decision, d.summary AS summary
ORDER BY name, decision
