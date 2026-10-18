MATCH (d:Decision {status:'active'})-[:ABOUT]->(:System {name:$system})
RETURN d.id AS id, d.summary AS summary, d.at AS at ORDER BY at DESC
