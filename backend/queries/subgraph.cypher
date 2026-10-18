MATCH (n) WHERE n.name IN $names OR n.id IN $names
OPTIONAL MATCH (n)-[r]-(m)
RETURN n, r, m
