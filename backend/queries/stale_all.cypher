MATCH (src:Source)-[:ASSUMES]->(old:Decision {status:'superseded'})
MATCH (old)<-[:SUPERSEDES*1..5]-(head:Decision {status:'active'})
OPTIONAL MATCH (src)-[:AUTHORED_BY]->(author:Person)
OPTIONAL MATCH (author)-[:MEMBER_OF]->(:Team)<-[:MEMBER_OF]-(mate:Person {status:'active'})
OPTIONAL MATCH (src)-[:MENTIONS]->(:System)<-[:MENTIONS]-(other:Source)-[:AUTHORED_BY]->(mate)
WITH src, old, head, author, mate, count(DISTINCT other) AS know
ORDER BY know DESC, id(mate)
WITH src, old, head, author, collect(mate.name) AS mates
RETURN src.id AS source_id, src.title AS stale_doc, src.kind AS kind,
       old.id AS old_id, old.summary AS assumes,
       head.id AS now_id, head.summary AS now_true, head.at AS changed_at,
       author.name AS author, author.status AS author_status,
       CASE WHEN author.status = 'active' THEN [author.name] ELSE mates[..2] END AS fix_by
ORDER BY changed_at DESC, source_id
