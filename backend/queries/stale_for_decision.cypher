MATCH (new:Decision {id:$did})-[:SUPERSEDES]->(old:Decision)<-[:ASSUMES]-(src:Source)
OPTIONAL MATCH (src)-[:AUTHORED_BY]->(author:Person)
OPTIONAL MATCH (author)-[:MEMBER_OF]->(:Team)<-[:MEMBER_OF]-(mate:Person {status:'active'})
OPTIONAL MATCH (src)-[:MENTIONS]->(:System)<-[:MENTIONS]-(other:Source)-[:AUTHORED_BY]->(mate)
WITH src, old, new, author, mate, count(DISTINCT other) AS know
ORDER BY know DESC, id(mate)
WITH src, old, new, author, collect(mate.name) AS mates
RETURN src.id AS source_id, src.title AS stale_doc, src.kind AS kind,
       old.id AS old_id, old.summary AS assumes,
       new.id AS now_id, new.summary AS now_true, author.name AS author, author.status AS author_status,
       CASE WHEN author.status = 'active' THEN [author.name] ELSE mates[..2] END AS fix_by
ORDER BY source_id
