UNWIND $projects AS p
CREATE (pr:Project {name: p.name, description: p.description})
WITH pr, p
UNWIND p.uses AS u
MATCH (s:System {name: u})
CREATE (pr)-[:USES]->(s)
