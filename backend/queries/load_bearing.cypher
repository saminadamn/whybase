CALL algo.pageRank('Decision', 'RELIES_ON')
YIELD node, score
RETURN node.id AS id, node.summary AS decision, node.status AS status, score
ORDER BY score DESC LIMIT $limit
