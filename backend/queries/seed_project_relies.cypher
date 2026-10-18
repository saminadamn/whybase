UNWIND $pairs AS pair
MATCH (a:Project {name: pair[0]}), (b:Decision {id: pair[1]})
CREATE (a)-[:RELIES_ON]->(b)
