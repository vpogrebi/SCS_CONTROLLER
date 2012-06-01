'''
Created on Jul 14, 2009

@author: valeriypogrebitskiy

job.py implements job related functionality. This functionality is implemented
by job.Job class which is responsible for all aspects of job operation: 

    - job and job step initialization
    - job execution (executing individual job steps in a certain sequence)
    - handling individual job step completion (success or failure) events
    - logging detailed job information to log and error file
    - saving job info in the database (scs.job table) 
'''
__docformat__ = 'epytext'

import workflow
import deferred_lib
import twisted_logger

from job_step import JobStep
from mysqldb import TwistedMySQLdb
from twisted.python.failure import Failure
from twisted.internet import defer, reactor

timeoutFlag = True

class Job(object):
    """Implements job functionality responsible for executing and orchestrating multiple job steps.
    
    Constructor argument(s):
    
    @param workFlow: workflow that started the job
    @type workFlow: workflow.Workflow instance
    """
    def __init__(self, workFlow, logName = None):
        if not isinstance(workFlow, workflow._Workflow):
            err_msg = "workflow._Workflow instance is expected (%s is passed instead)" % workFlow.__class__.__name__
            raise RuntimeError, err_msg
        
        self.steps = []
        self.callID = None
        self.deferred = None
        self.logName = logName
        self.workflow = workFlow
        self.jobStepDeferreds = []
        self.db = TwistedMySQLdb()
        
        self.jobID = None
        self.input = None
        self.status = None
        self.output = None
        self.error = None
        # Set Job's deferred
        self.deferred = defer.Deferred()
        # Set initial log prefix
        self.logPrefix = "WORKFLOW: '%s', JOB: <UNINITIALIZED>" % workFlow.name

    def __failure(self, nothing, err_msg):
        "Last part of Job's failure handler"
        msg = "Job has failed: %s" % err_msg
        twisted_logger.writeErr(self.logPrefix, self.logName, msg)
        if self.deferred and self.deferred.called == 0:            
            self.deferred.errback(Failure(err_msg, RuntimeError))

    def __success(self, nothing):
        "Last part of Job's success handler"
        log_msg = "Job has successfully completed"            
        twisted_logger.writeLog(self.logPrefix, self.logName, log_msg)
        if self.deferred and self.deferred.called == 0:            
            self.deferred.callback(self.output)

    def __initJobSteps(self, jobID):
        "Initialize individual job steps (JobStep entities) corresponding to a given job"
        self.jobID = int(jobID)
        self.logPrefix = "WORKFLOW: %s, JOB: #%d" % (self.workflow.name, self.jobID)
        initDeferreds = []

        numSteps = len(self.workflow.steps)
        for stepNo in range(numSteps):
            try:
                jobStep = JobStep(self.workflow, self.jobID, self.workflow.steps[stepNo], self.logName)
                initDeferreds.append(jobStep.init())
            except RuntimeError, err:
                raise RuntimeError, err
            
            if stepNo < numSteps - 1:
                # Add <self.runJobStep()> callback method to given job step's deferred
                jobStep.deferred.addCallback(self.runJobStep, stepNo + 1)
                    
            self.steps.append(jobStep)
            # Add given job step's deferred to <self.__jobStepDeferreds> list
            self.jobStepDeferreds.append(jobStep.deferred)

        if len(self.jobStepDeferreds) > 0:
            # Set callback method to be executed when all job steps have completed
            defer.DeferredList(self.jobStepDeferreds).addCallback(self.successHandler)

        return defer.DeferredList(initDeferreds)
            
    def __handleDBFailure(self, fail, stmt, type):
        "Record <scs.job_step> insert/update failure details"
        operationType = {'insert': 'inserting into', 'update': 'updating'}
        err_msg = "Failure %s <scs.job> table: %s" % (operationType[type], fail.getErrorMessage())
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        twisted_logger.writeErr(self.logPrefix, self.logName, stmt)
    
    def _timeout(self):
        "Job timeout event handler"
        # Cancel all job steps tha have not been executed yet
        for deferred in self.jobStepDeferreds:
            if deferred.called == 0:
                # Delete job step deferreds that have not yet been executed (callback/errback) - so that
                # subsequent job steps will not be executed
                # IMPORTANT: client_request.JobRequest class should verify whether JobRequest 
                # instance has <deferred> attribute - before attempting to execute its callback/errback
                del deferred
                        
        # Execute <self.failureHandler()> to process job failure event
        self.failureHandler(Failure("job timed out", RuntimeError))

    def _setTimeout(self, timeout):
        "Set or update previously set job timeout (number of seconds) setting"
        if self.callID:
            if self.callID.called == 0 and not self.callID.cancelled:
                # Cancel previously scheduled job timeout verification
                self.callID.cancel()
            del self.callID
            self.callID = None
            
        if timeoutFlag:
            self.callID = reactor.callLater(timeout, self._timeout)
        
    def init(self):
        """Synchronous job initialization
        
        @return: deferred - a Deferred which will fire None or a Failure when database INSERT statement is complete.
                            Once this deferred is called back, self.__initJobSteps() gets executed that returns
                            another deferred - which fire when all of the JobStep instances are initiated
        """
        # Set initial status to 'NEW'
        self.status = 'NEW'
        # Insert new record into <scs.job> table
        stmt = "insert scs.job (status, wf_name) values ('%s', '%s')" % (self.status, self.workflow.name)
        return self.db.insert(stmt).addCallback(self.__initJobSteps)
        
    def run(self, request, ext_deferred):
        """Start asynchronous job exection by executing first job step
        
        @return: deferred (twisted.internet.defer.Deferred instance) which will 'fire' when first JobStep has been started
        """
        self.input = request
        # Set <self.deferred> to the supplied external (SCSServer entity's) deferred
        self.deferred = ext_deferred        

        if self.steps == []:
            err_msg = "Job #%d does not include any job steps" % self.jobID
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            return Failure(err_msg, RuntimeError)
        else:
            # Start first job step's execution
            return self.runJobStep(None)
                
    def done(self, err_msg = None):
        """Perform JobStep's finalization tasks. Completion of this method should trigger Job 
        instance's callback() or errback() attached to <self.deferred>
        
        @return: deferred which will 'fire' when job completion has been processed and scs.scs_job table updated
        """
        
        # Cancel (potentially) scheduled job timeout verification
        if self.callID and self.callID.called == 0 and self.callID.cancelled == 0:
            self.callID.cancel()
        
        # Update scs.job table with job's execution information
        if self.output:
            if err_msg is None:
                stmt = "update scs.job set status = '%s', output = '%s', end_time = now() where " \
                        "job_id = %d" % (self.status, str(self.output).replace("'", "''"), self.jobID)
            else:
                stmt = "update scs.job set status = '%s', output = '%s', end_time = now(),  error = '%s' " \
                        "where job_id = %d" % (self.status, str(self.output).replace("'", "''"), err_msg.replace("'", "''"), self.jobID)
        else:
            if err_msg is None:
                stmt = "update scs.job set status = '%s', end_time = now() where " \
                        "job_id = %d" % (self.status, self.jobID)
            else:
                stmt = "update scs.job set status = '%s', end_time = now(),  error = '%s' " \
                        "where job_id = %d" % (self.status, err_msg.replace("'", "''"), self.jobID)
            
        deferred = self.db.execute(stmt).addErrback(self.__handleDBFailure, stmt, 'update')
        if self.status == 'FAILURE':
            deferred.addCallback(self.__failure, err_msg)
        else:
            deferred.addCallback(self.__success)
     
        return deferred
    
    def runJobStep(self, result, step_no = 0):
        """Start asynchronous job step (<step_no>) execution
        
        @return: deferred which will 'fire' when given JobStep instance has started execution
        """
        def updateJobStatus(res):
            "Update job status to 'RUNNING'"
            self.status = 'RUNNING'
            stmt = "update scs.job set status = '%s', text_input = '%s', start_time = now() " \
                    "where job_id = %d" % (self.status, self.input.replace("'", "''"), self.jobID)
            self.db.execute(stmt).addErrback(self.__handleDBFailure, stmt, 'update')
            
            # Schedule job timeout check using workflow's <timeout> attribute
            if timeoutFlag and self.workflow.timeout:
                self.callID = reactor.callLater(self.workflow.timeout, self._timeout)
                                    
        step = self.steps[step_no]
        if step_no == 0:
            request = self.input
        else:
#            if isinstance(self.steps[step.inputSource - 1].output, dict):
#                request = eval(self.steps[step.inputSource - 1].output)
#            else:
            request = self.steps[step.inputSource - 1].output
                
        # Add <self.failureHandler()> errback method to given job step's deferred
        step.deferred.addErrback(self.failureHandler)

        # Execute job step's run() and add <self.failureHandler()> errback to it - to handle job failure event
        twisted_logger.writeLog(self.logPrefix, self.logName, "Executing job step #%d... " % (step_no + 1))
        if step_no == 0:
            return step.run(request).addCallback(updateJobStatus).addErrback(self.failureHandler)
        else:
            return step.run(request).addErrback(self.failureHandler)
            
    def failureHandler(self, failure):
        "Handle job step failure event"
        err_msg = failure.getErrorMessage()
        self.error = err_msg
        self.status = 'FAILURE'
        self.done(err_msg)

    def successHandler(self, result):
        "Handle job step success event"        
        self.status = 'SUCCESS'
        for jobStep in self.steps:
            if jobStep.lastStep:
                self.output = jobStep.output
                break
        self.done(None)
