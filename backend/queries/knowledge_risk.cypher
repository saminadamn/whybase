MATCH (s:System)<-[:MENTIONS]-(:Source)-[:AUTHORED_BY]->(p:Person)
WITH s, collect(DISTINCT p) AS people
WITH s, [x IN people WHERE x.status = 'active' | x.name] AS active,
        [x IN people WHERE x.status = 'left'   | x.name] AS gone
WHERE size(active) <= 1
RETURN s.name AS system, active, gone
ORDER BY size(gone) DESC, system
