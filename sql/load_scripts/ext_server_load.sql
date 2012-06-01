insert ext_server (server_name, host, port, protocol, description) values ('EES_SERVER', 'localhost', 7000, 'TCP', 'Entity Extraction Server (EES)');
insert ext_server (server_name, host, port, protocol, description) values ('CTS_SERVER', '', 7001, 'TCP', 'Concept Tagging Server (CTS)');
insert ext_server (server_name, host, port, protocol, description) values ('MCTS_SERVER', '', 7002, 'TCP', 'Media Channel Tagging Server (MCTS)');
insert ext_server (server_name, host, port, protocol, description) values ('QLS_SERVER', '', 7003, 'TCP', 'Query Logic Server (QLS)');