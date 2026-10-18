MATCH (s:System {name:$system}), (old:Decision {id:$old}), (p:Person {name:$author})
CREATE (src:Source {id:$sid, kind:'chat', title:$title, text:$text, at:$at})-[:AUTHORED_BY]->(p)
CREATE (d:Decision {id:$did, summary:$summary, at:$at, status:'active'})-[:RECORDED_IN]->(src)
CREATE (d)-[:ABOUT]->(s), (d)-[:MADE_BY]->(p), (d)-[:SUPERSEDES]->(old), (src)-[:MENTIONS]->(s)
SET old.status = 'superseded', old.superseded_at = $at
RETURN d.id AS id
