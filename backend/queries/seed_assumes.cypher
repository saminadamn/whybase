UNWIND $pairs AS pair
MATCH (a:Source {id: pair[0]}), (b:Decision {id: pair[1]})
CREATE (a)-[:ASSUMES]->(b)
