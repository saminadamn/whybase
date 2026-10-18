MATCH p = (x)-[:RELIES_ON*1..3]->(:Decision {id:$id})
RETURN DISTINCT coalesce(x.name, x.id) AS affected,
       CASE WHEN x:Project THEN 'Project' ELSE 'Decision' END AS kind,
       coalesce(x.summary, x.description) AS detail,
       length(p) AS hops,
       [n IN nodes(p) | coalesce(n.name, n.id)] AS via
ORDER BY hops, affected
