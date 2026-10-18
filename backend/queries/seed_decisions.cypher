UNWIND $decisions AS d
MATCH (s:System {name: d.about}), (p:Person {name: d.made_by}), (src:Source {id: d.recorded_in})
CREATE (n:Decision {id: d.id, summary: d.summary, at: d.at, status: d.status, superseded_at: d.superseded_at})
CREATE (n)-[:RECORDED_IN]->(src), (n)-[:ABOUT]->(s), (n)-[:MADE_BY]->(p)
