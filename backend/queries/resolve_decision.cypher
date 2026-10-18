MATCH (d:Decision)
WHERE d.id = toUpper($q) OR toLower(d.summary) CONTAINS toLower($q)
RETURN d.id AS id, d.summary AS summary, d.status AS status
ORDER BY d.at DESC LIMIT 3
