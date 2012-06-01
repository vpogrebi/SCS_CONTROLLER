insert into workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WF', 'EES_CLIENT', 1, 0, False, False);
insert into workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WF', 'CTS_CLIENT', 2, 1, False, False);
insert into workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WF', 'MCTS_CLIENT', 3, 2, True, False);
insert into workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WF', 'QLS_CLIENT', 4, 3, False, False);

insert into workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('PORTER_WF', 'EES_CLIENT', 1, 0, False, False);
insert into workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('PORTER_WF', 'CTS_CLIENT', 2, 1, True, False);