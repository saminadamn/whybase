UNWIND $sources AS s
MATCH (a:Person {name: s.author})
CREATE (src:Source {id: s.id, kind: s.kind, title: s.title, at: s.at, text: s.text,
                    reviewed_at: s.reviewed_at, reviewed_by: s.reviewed_by})-[:AUTHORED_BY]->(a)
WITH src, s
UNWIND s.mentions AS m
MATCH (sys:System {name: m})
CREATE (src)-[:MENTIONS]->(sys)
