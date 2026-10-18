MATCH (s:Source) WHERE s.id IN $ids
OPTIONAL MATCH (s)-[:AUTHORED_BY]->(p:Person)
RETURN s.id AS id, s.title AS title, s.kind AS kind, s.at AS at, p.name AS author
