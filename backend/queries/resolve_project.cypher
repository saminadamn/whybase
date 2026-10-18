MATCH (n:Project) WHERE toLower(n.name) = toLower($name) RETURN n.name AS name
