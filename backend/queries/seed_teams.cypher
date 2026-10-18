UNWIND $teams AS t
CREATE (:Team {name: t.name})
