'''
Created on Jul 16, 2009

@author: valeriypogrebitskiy

job_step.py implements job step related functionality. This functionality is implemented
by job_step.JobStep class which is responsible for all aspects of job step operation: 

    - job step initialization
    - job step execution (generating proper REQUEST and sending that request to remote external server)
    - handling job step completion (success or failure) events and notifying parent Job instance ('firing' job's deferred)
    - logging detailed job step information to log and error file
    - saving job step info in the database (scs.job_step table) 
'''
__docformat__ = 'epytext'

import client
import deferred_lib
import twisted_logger

from twisted.internet import defer
from mysqldb import TwistedMySQLdb
from twisted.python.failure import Failure

class JobStep(object):
    """JobStep class - implements individual job step's functionality. Multiple (potentially) instances of this class
    belong to a single job. JobStep instances are initialized and orchestrated by a job.Job class.
    """
    def __init__(self, workflow, jobID, info, logName = None):
        """Class's contructor. Parameters:
        
        @param workflow: Workflow instance
        @type workflow: C{workflow.Workflow} instance
        @param jobID: jobid
        @type jobID: int
        @param info: Dictionary containing job step's information  
        @type info: C{dict} containing following keys: {'stepID', 'stepNo', 'client', 'input_src', 'out_flag'}
        @param logName: name used to identify log/error files being used by given JobStep instance  
        """
        self.input = None
        self.output = None
        self.status = "NEW"
        self.jobID = jobID
        self.logName = logName
        self.workflow = workflow
        self.db = TwistedMySQLdb()
                
        self.stepID = info['stepID']
        self.client = info['clientName']
        self.stepNo = info['stepNo']
        self.lastStep = info['outFlag']
        self.inputSource = info['inputSrc']
    
        # Set JobStep's deferred and add callback() and errback() methods to it
        self.deferred = defer.Deferred()
        self.deferred.addCallback(self.successHandler).addErrback(self.failureHandler)                

        # Set logger
        self.logPrefix = 'JOB: #%d, STEP: #%d' % (self.jobID, self.stepNo)

    def __failure(self, nothing, err_msg):
        "Last part of JobStep's failure handler"
        msg = "Job step (%s) has failed: %s" % (self.client, err_msg)
        twisted_logger.writeErr(self.logPrefix, self.logName, msg)
        return Failure(err_msg, RuntimeError)

    def __success(self, nothing):
        "Last part of JobStep's success handler"
        msg = "Job step (%s) has successfully completed" % self.client            
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        return None

    def __handleDBFailure(self, fail, stmt, type):
        "Record <scs.job_step> insert/update failure details"
        operationType = {'insert': 'inserting into', 'update': 'updating'}
        err_msg = "Failure %s <scs.job_step> table: %s" % (operationType[type], fail.getErrorMessage())
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
    
    def init(self):
        "Initialization: Insert new record into <scs.job_step> table"
        stmt = "insert scs.job_step (job_id, step_id, status) values " \
            "(%d, %d, '%s')" % (self.jobID, self.stepID, self.status)
        return self.db.execute(stmt).addErrback(self.__handleDBFailure, stmt, 'insert')

    def run(self, request):
        """Start current job step's execution by sending request (<input>) to remote server
        
        @param request: request to be sent to external server
        @type request: dict {'scs_jobid': <jobid>, 'request': <request_data (text)>}
        
        @return: deferred - a Deferred which will fire None or a Failure when database UPDATE statement is complete
        """
        error = None
        self.input = request
        request = {'scs_jobid': self.jobID, 'request': request}

        try:
            client.SCSClientManager().sendRequest(self.client, request, self.deferred)
        except Exception, err:
            error = str(err)
            self.status = 'FAILURE'
            stmt = "update scs.job_step set status = '%s', text_input = '%s', error = '%s', start_time = now(), " \
                    "end_time = now() where job_id = %d and step_id = %d" % (self.status, str(self.input).replace("'", "''"), 
                                                                             error.replace("'", "''"), self.jobID, self.stepID)
        else:
            self.status = 'RUNNING'            
            stmt = "update scs.job_step set status = '%s', text_input = '%s', start_time = now() " \
                    "where job_id = %d and step_id = %d" % (self.status, str(self.input).replace("'", "''"), self.jobID, self.stepID)

        deferred = self.db.execute(stmt).addErrback(self.__handleDBFailure, stmt, 'update')
                
        if self.status == 'FAILURE':
            deferred.addCallback(self.__failure, error)
        
        return deferred
        
    def done(self, err_msg = None):
        """Perform JobStep's finalization tasks. Completion of this method should trigger Job 
        instance's callback() or errback() attached to <self.deferred>
        
        @attention: This method should either throw RuntimeError exception, or return some (any)
                    value indicating success. This should trigger Job instance's  
                    errback() or callback() method  - if one was added to <self.deferred> 
                    by the Job instance before JobStep's run() is executed 
    
        @return: deferred - a Deferred which will fire None or a Failure upon UPDATE database completion
        """

        # Update scs.job_step table with job step information
        if self.output:
            if err_msg is None:
                stmt = "update scs.job_step set status = '%s', output = '%s', end_time = now() where " \
                        "job_id = %d and step_id = %d" % (self.status, str(self.output).replace("'", "''"), self.jobID, self.stepID)
            else:
                stmt = "update scs.job_step set status = '%s', output = '%s', end_time = now(),  error = '%s' " \
                        "where job_id = %d and step_id = %d" % (self.status, str(self.output).replace("'", "''"), 
                                                                err_msg.replace("'", "''"), self.jobID, self.stepID)
    
        else:
            if err_msg is None:
                stmt = "update scs.job_step set status = '%s', end_time = now() where " \
                        "job_id = %d and step_id = %d" % (self.status, self.jobID, self.stepID)
            else:
                stmt = "update scs.job_step set status = '%s', end_time = now(), error = '%s' " \
                        "where job_id = %d and step_id = %d" % (self.status, err_msg.replace("'", "''"), self.jobID, self.stepID)
    
        deferred = self.db.execute(stmt).addErrback(self.__handleDBFailure, stmt, 'update')
            
#===============================================================================
#            IMPORTANT: Either throw RuntimeError exception, or return some (any)
#            value indicating success. This should trigger either Job instance's  
#            errback() or callback() method  - if one was added to <self.deferred> 
#            by the Job instance before JobStep's run() is executed
#===============================================================================
        if self.status == 'FAILURE':
            deferred.addCallback(self.__failure, err_msg)
        else:
            deferred.addCallback(self.__success)

        return deferred
    
    def failureHandler(self, failure):
        "Handle job step failure event"
        err_msg = failure.getErrorMessage()
        self.status = 'FAILURE'
        failure.trap(RuntimeError)
        return self.done(err_msg)

    def successHandler(self, result):
        "Handle job step success event"
        self.status = 'SUCCESS'
        self.output = result
        return self.done(None)
