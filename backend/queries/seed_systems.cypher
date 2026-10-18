UNWIND $systems AS s
MATCH (t:Team {name: s.team})
CREATE (t)-[:OWNS]->(:System {name: s.name, description: s.description})
