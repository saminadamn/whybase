MATCH (src:Source {id:$sid})-[r:ASSUMES]->(old:Decision {id:$old_id})
MATCH (old)<-[:SUPERSEDES*1..5]-(head:Decision {status:'active'})
DELETE r
CREATE (src)-[:ASSUMES]->(head)
SET src.reviewed_at = $now, src.reviewed_by = $by
RETURN src.id AS source_id, head.id AS now_assumes
