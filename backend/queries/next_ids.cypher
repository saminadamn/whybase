MATCH (d:Decision)
WITH max(d.id) AS max_decision
OPTIONAL MATCH (s:Source) WHERE s.id STARTS WITH 'S-CHAT-'
RETURN max_decision, max(s.id) AS max_chat
