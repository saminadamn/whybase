MATCH (old:Decision {id:$id})<-[:SUPERSEDES*1..5]-(head:Decision {status:'active'})
RETURN head.id AS id, head.summary AS summary, head.at AS at
