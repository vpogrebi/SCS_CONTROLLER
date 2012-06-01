SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='TRADITIONAL';

CREATE SCHEMA IF NOT EXISTS scs;

CREATE  TABLE IF NOT EXISTS `scs`.`workflow_lookup` (
  `wf_name` VARCHAR(45) NOT NULL ,
  `description` VARCHAR(45) NOT NULL ,
  `enabled` TINYINT(1) NOT NULL DEFAULT False ,
  `job_timeout` INT(11) NOT NULL DEFAULT 120 ,
  PRIMARY KEY (`wf_name`) )
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci;

insert into scs.workflow_lookup (wf_name, description, enabled) values('DORTHY_WORKFLOW', 'Dorthy.com Service Workflow', 1);
insert into scs.workflow_lookup (wf_name, description, enabled) values('PORTER_WORKFLOW', 'Porter Service Workflow', 0);
insert into scs.workflow_lookup (wf_name, description, enabled) values('TRAINING_WORKFLOW', 'Training Service Workflow', 0);
insert into scs.workflow_lookup (wf_name, description, enabled) values('CONTENT_WORKFLOW', 'Other Content Service Workflow', 0);
insert into scs.workflow_lookup (wf_name, description, enabled) values ('ADMIN_WORKFLOW', 'Administration Service Workflow', 0);

CREATE  TABLE IF NOT EXISTS `scs`.`scs_server` (
  `server_name` VARCHAR(45) NOT NULL ,
  `wf_name` VARCHAR(45) NOT NULL ,
  `port` INT(11) NOT NULL ,
  `protocol` VARCHAR(45) NOT NULL DEFAULT 'TCP' ,
  `max_connections` INT(11) NOT NULL DEFAULT 100 ,
  `description` VARCHAR(45) NOT NULL ,
  `enabled` TINYINT(1) NOT NULL DEFAULT False ,
  PRIMARY KEY (`server_name`) ,
  INDEX `fk_wf_name` (`wf_name` ASC) ,
  CONSTRAINT `fk_wf_name`
    FOREIGN KEY (`wf_name` )
    REFERENCES `scs`.`workflow_lookup` (`wf_name` )
    ON UPDATE CASCADE)
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci;

insert into scs.scs_server (server_name, port, wf_name, protocol, description, enabled) values ('DORTHY_SERVER', 9000, 'DORTHY_WORKFLOW', 'TCP', 'Dorthy.com SCS Server', 1);
insert into scs.scs_server (server_name, port, wf_name, protocol, description, enabled) values ('PORTER_SERVER', 9001, 'PORTER_WORKFLOW', 'TCP', 'Porter SCS Server', 0);
insert into scs.scs_server (server_name, port, wf_name, protocol, description, enabled) values ('TRAINING_SERVER', 9002, 'TRAINING_WORKFLOW', 'TCP', 'Training SCS Server', 0);
insert into scs.scs_server (server_name, port, wf_name, protocol, description, enabled) values ('ADMIN_SERVER', 9003, 'ADMIN_WORKFLOW', 'TCP', 'Admin SCS Server', 0);
insert into scs.scs_server (server_name, port, wf_name, protocol, description, enabled) values ('CONTENT_SERVER', 9004, 'CONTENT_WORKFLOW', 'TCP', 'Content SCS Server', 0);

CREATE  TABLE IF NOT EXISTS `scs`.`ext_client` (
  `client_name` VARCHAR(45) NOT NULL ,
  `server_name` VARCHAR(45) NOT NULL ,
  `description` VARCHAR(45) NOT NULL ,
  PRIMARY KEY (`client_name`) ,
  INDEX `fk_scs_server` (`server_name` ASC) ,
  CONSTRAINT `fk_scs_server`
    FOREIGN KEY (`server_name` )
    REFERENCES `scs`.`scs_server` (`server_name` )
    ON UPDATE CASCADE)
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci
COMMENT = 'SCS External Clients';

insert into scs.ext_client (client_name, server_name, description) values ('DORTHY_CLIENT', 'DORTHY_SERVER', 'Dorthy.com External Client');
insert into scs.ext_client (client_name, server_name, description) values ('PORTER_CLIENT', 'PORTER_SERVER', 'Porter External Client');
insert into scs.ext_client (client_name, server_name, description) values ('TRAINING_CLIENT', 'TRAINING_SERVER', 'Training External Client');
insert into scs.ext_client (client_name, server_name, description) values ('ADMIN_CLIENT', 'ADMIN_SERVER', 'Admin External Client');
insert into scs.ext_client (client_name, server_name, description) values ('CONTENT_CLIENT', 'CONTENT_SERVER', 'Other Content External Client');

CREATE  TABLE IF NOT EXISTS `scs`.`ext_server` (
  `server_name` VARCHAR(45) NOT NULL ,
  `host` VARCHAR(45) NULL DEFAULT NULL ,
  `port` INT(11) NOT NULL ,
  `protocol` VARCHAR(45) NOT NULL ,
  `description` VARCHAR(45) NOT NULL ,
  PRIMARY KEY (`server_name`) )
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci
COMMENT = 'SCS External Servers - where job steps are executed';

insert into scs.ext_server (server_name, host, port, protocol, description) values ('EES_SERVER', 'blackbird.s7', 10000, 'TCP', 'Entity Extraction Server (EES)');
insert into scs.ext_server (server_name, host, port, protocol, description) values ('CTS_SERVER', 'blackbird.s7', 10001, 'TCP', 'Concept Tagging Server (CTS)');
insert into scs.ext_server (server_name, host, port, protocol, description) values ('MCTS_SERVER', '', 10002, 'TCP', 'Media Channel Tagging Server (MCTS)');
insert into scs.ext_server (server_name, host, port, protocol, description) values ('QLS_SERVER', '', 10003, 'TCP', 'Query Logic Server (QLS)');

CREATE  TABLE IF NOT EXISTS `scs`.`scs_client` (
  `client_name` VARCHAR(45) NOT NULL ,
  `server_name` VARCHAR(45) NOT NULL ,
  `description` VARCHAR(60) NOT NULL ,
  `enabled` TINYINT(1) NOT NULL DEFAULT False ,
  PRIMARY KEY (`client_name`) ,
  INDEX `fk_ext_server` (`server_name` ASC) ,
  CONSTRAINT `fk_ext_server`
    FOREIGN KEY (`server_name` )
    REFERENCES `scs`.`ext_server` (`server_name` )
    ON DELETE RESTRICT
    ON UPDATE CASCADE)
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci;

insert into scs.scs_client (client_name, server_name, description, enabled) values ('EES_CLIENT', 'EES_SERVER', 'Entity Extraction System (EES) SCS Client', 1);
insert into scs.scs_client (client_name, server_name, description, enabled) values ('CTS_CLIENT', 'CTS_SERVER', 'Concept Tagging System (CTS) SCS Client', 1);
insert into scs.scs_client (client_name, server_name, description, enabled) values ('MCTS_CLIENT', 'MCTS_SERVER', 'Media Channel Tagging System (MCTS) SCS Client', 0);
insert into scs.scs_client (client_name, server_name, description, enabled) values ('QLS_CLIENT', 'QLS_SERVER', 'Query Logic System (QLS) SCS Client', 0);

CREATE  TABLE IF NOT EXISTS `scs`.`workflow_step` (
  `step_id` INT(11) NOT NULL AUTO_INCREMENT ,
  `wf_name` VARCHAR(45) NOT NULL ,
  `client_name` VARCHAR(45) NOT NULL ,
  `step_no` INT(11) NOT NULL ,
  `input` INT(11) NOT NULL ,
  `out_flag` TINYINT(1) NOT NULL DEFAULT '0' ,
  `enabled` TINYINT(1) NOT NULL DEFAULT '1' COMMENT 'True/False flag indicating if given workflow step is enabled' ,
  PRIMARY KEY (`step_id`, `wf_name`, `step_no`) ,
  INDEX `fk_client_name` (`client_name` ASC) ,
  INDEX `fk_wf_name1` (`wf_name` ASC) ,
  INDEX `fk_scs_client` (`client_name` ASC) ,
  UNIQUE INDEX `uniq_step` (`wf_name` ASC, `client_name` ASC) ,
  CONSTRAINT `fk_scs_client`
    FOREIGN KEY (`client_name` )
    REFERENCES `scs`.`scs_client` (`client_name` )
    ON DELETE RESTRICT
    ON UPDATE CASCADE,
  CONSTRAINT `fk_wf_name1`
    FOREIGN KEY (`wf_name` )
    REFERENCES `scs`.`workflow_lookup` (`wf_name` )
    ON DELETE RESTRICT
    ON UPDATE CASCADE)
ENGINE = InnoDB
AUTO_INCREMENT = 7
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci;

insert into scs.workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WORKFLOW', 'EES_CLIENT', 1, 0, False, True);
insert into scs.workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WORKFLOW', 'CTS_CLIENT', 2, 1, True, True);
insert into scs.workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WORKFLOW', 'MCTS_CLIENT', 3, 2, False, False);
insert into scs.workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('DORTHY_WORKFLOW', 'QLS_CLIENT', 4, 3, False, False);
insert into scs.workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('PORTER_WORKFLOW', 'EES_CLIENT', 1, 0, False, False);
insert into scs.workflow_step (wf_name, client_name, step_no, input, out_flag, enabled) values ('PORTER_WORKFLOW', 'CTS_CLIENT', 2, 1, True, False);

CREATE  TABLE IF NOT EXISTS `scs`.`job_status_lookup` (
  `status` VARCHAR(45) NOT NULL ,
  `description` VARCHAR(45) NOT NULL ,
  PRIMARY KEY (`status`) )
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci
COMMENT = 'Job Status Lookup';

insert into scs.job_status_lookup values ('NEW', 'New SCS job or job step');
insert into scs.job_status_lookup values ('RUNNING', 'SCS job or job step is being processed');
insert into scs.job_status_lookup values ('SUCCESS', 'Successful SCS job or job step completion');
insert into scs.job_status_lookup values ('FAILURE', 'SCS job or job step failure');

CREATE  TABLE IF NOT EXISTS `scs`.`job` (
  `job_id` INT(11) NOT NULL AUTO_INCREMENT ,
  `status` VARCHAR(45) NOT NULL ,
  `wf_name` VARCHAR(45) NOT NULL ,
  `text_input` TEXT NULL DEFAULT NULL ,
  `bin_input` BLOB NULL DEFAULT NULL ,
  `output` TEXT NULL DEFAULT NULL ,
  `error` VARCHAR(200) NULL DEFAULT NULL ,
  `start_time` TIMESTAMP NULL DEFAULT NULL ,
  `end_time` TIMESTAMP NULL DEFAULT NULL ,
  PRIMARY KEY (`job_id`) ,
  INDEX `fk_job_status1` (`status` ASC) ,
  INDEX `fk_wf_name2` (`wf_name` ASC) ,
  CONSTRAINT `fk_job_status1`
    FOREIGN KEY (`status` )
    REFERENCES `scs`.`job_status_lookup` (`status` )
    ON UPDATE CASCADE,
  CONSTRAINT `fk_wf_name2`
    FOREIGN KEY (`wf_name` )
    REFERENCES `scs`.`workflow_lookup` (`wf_name` )
    ON UPDATE CASCADE)
ENGINE = InnoDB
DEFAULT CHARACTER SET = latin1
COLLATE = latin1_swedish_ci
COMMENT = 'SCS Job Info';

CREATE  TABLE IF NOT EXISTS `scs`.`job_step` (
  `job_id` INT(11) NOT NULL ,
  `step_id` INT(11) NOT NULL ,
  `status` VARCHAR(45) NOT NULL ,
  `text_input` TEXT NULL DEFAULT NULL ,
  `bin_input` BLOB NULL DEFAULT NULL ,
  `output` TEXT NULL DEFAULT NULL ,
  `error` VARCHAR(200) NULL DEFAULT NULL ,
  `start_time` TIMESTAMP NULL DEFAULT NULL ,
  `end_time` DATETIME NULL DEFAULT NULL ,
  INDEX `fk_job_status` (`status` ASC) ,
  INDEX `fk_step_id` (`step_id` ASC) ,
  INDEX `fk_job_id` (`job_id` ASC) ,
  PRIMARY KEY (`job_id`, `step_id`) ,
  CONSTRAINT `fk_job_status`
    FOREIGN KEY (`status` )
    REFERENCES `scs`.`job_status_lookup` (`status` )
    ON DELETE RESTRICT
    ON UPDATE CASCADE,
  CONSTRAINT `fk_step_id`
    FOREIGN KEY (`step_id` )
    REFERENCES `scs`.`workflow_step` (`step_id` )
    ON DELETE RESTRICT
    ON UPDATE CASCADE,
  CONSTRAINT `fk_job_id`
    FOREIGN KEY (`job_id` )
    REFERENCES `scs`.`job` (`job_id` )
    ON DELETE RESTRICT
    ON UPDATE CASCADE)
ENGINE = InnoDB
COLLATE = latin1_swedish_ci;

SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
