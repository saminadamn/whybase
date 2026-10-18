UNWIND $people AS p
MATCH (t:Team {name: p.team})
CREATE (:Person {name: p.name, role: p.role, status: p.status, left_at: p.left_at})-[:MEMBER_OF]->(t)
