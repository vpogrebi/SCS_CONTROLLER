'''
Created on Aug 14, 2009

@author: valeriypogrebitskiy
'''
__docformat__ = 'epytext'

import twisted_logger
from twisted.python import failure 
from zope.interface import implements
from twisted.internet import defer, task

# Set flag that dictates whether or not JobStatusRequest instances should schedule regular status checks
# @attention: Set scheduleChecks flag explicitly to False for testing purpose
scheduleChecks = True   

# Set falg that dictates whether or not JobRequest.__init__() should check correctness of request (execute _checkRequest())
# Set <checkRequest> to False explicitly if request check needs to be avoided
checkRequest = True

jobStatusMap = {'success': 0, 'failure': 1, 'running': None}

class JobRequest(object):
    """
    JobRequest class - responsible for processing JOB STEP requests that come from JobStep  
    instances when a job is being executed by SCSServer instance that handles external client's requests
    
    This class is responsible for following functionality related to job request management:
        1. Processing job request (sending request to external server)
        2. Scheduling regular job 'STATUS' requests (in a loop) with regular time intervals
        3. Handling job response - when it comes from the server

    """    
    def __init__(self, request, deferred, client):
        """
        JobRequest class's constructor
        
        @param request: request dat supplied by JobStep instance
        @type request:  dictionary containing following required data
                        {'scs_jobid': <jobid>, 'request': <request_data (text or YAML structure)>}
        @param deferred: external job step's deferred to be associated with the given request
        @type deferred: twisted.internet.defer.Deferred instance
        @param client: SCSClientProtocol instance that created this JobRequest entity
        @type client: SCSClientProtocol
                        
        @raise RuntimeError: (1) if invalid request is supplied, or 
                             (2) if supplied deferred is not a valid instance of defer.Deferred class
        """
        # Check if supplied deferred is a valid defer.Deferred instance
        if not deferred:
            err_msg = "external deferred is not supplied"
            raise RuntimeError, err_msg
        elif not issubclass(deferred.__class__, defer.Deferred):
            err_msg = "supplied deferred is %s (not a valid defer.Deferred instance)" % deferred.__class__
            raise RuntimeError, err_msg
        
        self.request = request
        # Add 'type' key/value to request data
        self.request['type'] = 'REQUEST'
        
        if checkRequest:
            try:
                self._checkRequest(request)
            except:
                raise

        self.error = None
        self.status = None
        self.stopped = False
        self.response = None
        self.accepted = False
        self.deferred = deferred
        self.clientProtocol = client
        self.scs_jobid = request['scs_jobid']
        
        # Initialize JobStatusRequest entity that will schedule and perform regular job status checks
        self.statusRequest = JobStatusRequest(self)
        
    def _stop(self):
        """JobRequest termination: 
            1. fire callback or errback method associated with request's deferred        
            2. perform cleanup
        """
        if not self.stopped:
            # Stop job status requests and remove such requests from factory's cachedRequests list (if any)
            self.statusRequest._stop()
            # Delete JobStatusRequest entity - to free up memory
            del self.statusRequest            
            self.stopped = True

            # Execute deferred's callback() or errback() to notify JobStep (and Job) instance of job step completion
            if hasattr(self, 'deferred') and self.deferred.called == 0:
                if self.status == 'FAILURE' and self.error:
                    msg = "Executing deferred's errback() to notify of job step failure"
                    twisted_logger.writeErr(self.clientProtocol.logPrefix, self.clientProtocol.logName, msg)
                    # Execute deferred's errback() to notify of job's failure
                    self.deferred.errback(failure.Failure(self.error, RuntimeError))
                elif self.status == 'SUCCESS':
                    msg = "Executing deferred's callback() to notify of job step success"
                    twisted_logger.writeLog(self.clientProtocol.logPrefix, self.clientProtocol.logName, msg)
                    # Execute deferred's callback() to notify of job's success
                    self.deferred.callback(self.response)
                else:
                    self.deferred.called = 1
                    
            else:
                msg = "Deferred's callback/errback has been canceled"
                twisted_logger.writeLog(self.clientProtocol.logPrefix, self.clientProtocol.logName, msg)
                                    
    def _failure(self, error):
        "Process job failure event. Executes self._stop() that fires self.deferred.errback()"
        if self.status is None:
            # Update job request's status and error attributes
            self.status = 'FAILURE'
            self.error = error
            err_msg = "Job step (job #%d) has failed: %s" % (self.scs_jobid, error)
            twisted_logger.writeErr(self.clientProtocol.logPrefix, self.clientProtocol.logName, err_msg)
            # Stop job request's processing
            self._stop()

    def _success(self):
        "Process job success event. Executes self._stop() that fires self.deferred.callback()"
        if self.status is None:
            self.status = 'SUCCESS'
            msg = "Job step (job #%d) has successfully completed" % self.scs_jobid
            twisted_logger.writeLog(self.clientProtocol.logPrefix, self.clientProtocol.logName, msg)
            # Stop job request's processing
            self._stop()

    def _checkRequest(self, request):
        """
        Verify that supplied request is a valid JOB STEP request
        
        @param request: request dat supplied by JobStep instance
        @type request:  dictionary containing following required data
                        {'scs_jobid': <jobid>, 'request': <request_data (text or YAML structure)>}
                        
        @raise RuntimeError: if invalid request is supplied 
        """
        requiredKeys = ['scs_jobid', 'request']
        validTypes = ['REQUEST', 'STATUS']

        for key in requiredKeys:
            if not request.has_key(key):
                err_msg = "request does not have '%s' data" % key
                raise RuntimeError, err_msg            

        if request['type'] not in validTypes:
            err_msg = "invalid request type ('%s'). Valid request types: %s" % (request['type'], validTypes)
            raise RuntimeError, err_msg
        
        if request['type'] == 'REQUEST' and not request.has_key('request'):
            err_msg = "job request does not contain 'request' data"
            raise RuntimeError, err_msg

    def _checkResponse(self, response):
        """
        Verify that supplied response is a valid job response
        
        @param response: response received from the server
        @type response: C{dict}
        
        @attention: <response> must be a dictionary containing following keys:
                    - 'status': <job status: 0, 1 or None>
                    - 'err_msg': <error message, or None>  
                    - 'result_set': <job result set (dictionary), or None>
                    Required data: 'status'
                    Optional data: 'err_msg', 'result_set'

        @raise RuntimeError: if invalid response is supplied 
        """
        requiredKeys = ['status']
        
        for key in requiredKeys:
            if not response.has_key(key):
                err_msg = "response does not have '%s' data" % key
                self._failure(err_msg)

        if response['status'] not in jobStatusMap.values():
            err_msg = "invalid job step status %s (valid statuses: %s)" % (response['status'], jobStatusMap.values())
        
    def processRequest(self):
        """
        Process job request - send request to external server

        @attention: This method simply executes self.clientProtocol.sendLine() of an SCSClientProtocol 
                    instance that created this JobRequest entity, passing in self.request
        """
        self.clientProtocol.sendLine(self.request)
    
    def processResponse(self, response):
        """
        Process job response
        
        @param response: response received from external server
        @type response: C{dict}
        
        @raise RuntimeError: (1) if invalid response is supplied
                             (2) if any exception is raised during processing response
        """
        try:
            self._checkResponse(response)
        except Exception, err:
            raise RuntimeError, err
            
        if response.has_key('result_set'):
            self.response = response['result_set']
                
        if response['status'] != 0:
            err_msg = "Unknown error"
            if response.has_key('err_msg'):
                if response['err_msg']:
                    err_msg = response['err_msg'].strip()
            self._failure(err_msg)
        else:
            self._success()

            
class JobStatusRequest(object):
    """
    JobStatusRequest class responsible for processing JOB STATUS requests that are initiated by the  
    client with regular time intervals - to check the status of that job on a server side 
    
    Constructor parameters and failure conditions:
    
    @param jobRequest: JobRequest instance that "owns" given JobStatusRequest
    """
    
    def __init__(self, jobRequest):
        """
        Constructor. Parameters:
        
        @param jobRequest: JobRequest instance that "owns" given JobStatusRequest
        """
        self.loop = None
        self.checkInterval = 10  # Default job status request interval
        self.jobRequest = jobRequest
        self.request = {'type': 'STATUS'}
        
    def _stop(self):
        "Stop job status checking and remove this request from factory's cachedRequests list (if it s in that list)"
        # Cancel scheduled job status checks
        if self.loop:
            self.loop.stop()
        # Free reference to "parent" job request entity
        self.jobRequest = None
        
    def _checkRequest(self, request):
        """
        Does nothing - in case of client's JobStatusRequest, 'STATUS' request itself is being generated by 
        the class's constructor (self.__init__()), hence - no need to verify its correctness""" 
        pass
    
    def _checkResponse(self, response):
        """
        Verify that supplied response has correct format and required data
        
        @param response: supplied response
        @type response: YAML data structure loaded using yaml.load()
                        It must be a dictionary containing two or three key/value pairs: 
                        {'status': <job status>, 'err_msg': <error message if any>}
                        Optional key: 'err_msg'
        @raise RuntimeError: if invalid response is supplied
        """
        requiredKeys = ['status']
        
        for key in requiredKeys:
            if not response.has_key(key):
                err_msg = "response does not have '%s' data" % key
                raise RuntimeError, err_msg
        
    def _startStatusChecks(self, now = False):
        "Schedule job status requests to run in a loop with given time interval"
        self.loop = task.LoopingCall(self.processRequest)
        self.loop.start(self.checkInterval, now)

    def processRequest(self):
        """
        Process given job status request
        
        @attention: This method is scheduled (by the JobRequest entity that created this JobStatusRequest instance)
                    to run in a loop (with the given time interval). It simply executes self.clientProtocol.sendLine() 
                    of an SCSClientProtocol instance that created this JobStatusRequest entity, passing in itself
        """
        msg = "Sending job status request (job #%d) to '%s' server" % (self.jobRequest.scs_jobid, self.jobRequest.clientProtocol.peer)
        twisted_logger.writeLog(self.jobRequest.clientProtocol.logPrefix, self.jobRequest.clientProtocol.logName, msg)
        try:
            self.jobRequest.clientProtocol.sendLine(self.request)
        except Exception, err:
            err_msg = "Unable to send job status request corresponding to job #%d: %s" % (self.jobRequest.scs_jobid, str(err))
            twisted_logger.writeErr(self.jobRequest.clientProtocol.logPrefix, self.jobRequest.clientProtocol.logName, err_msg)
        
    def processResponse(self, response):
        """
        Process response data obtained in response to a given request
        
        @param response: response
        @raise RuntimeError: (1) if invalid response is supplied
                             (2) if any exception is raised during response processing 
        """
        try:
            self._checkResponse(response)
        except Exception, err:
            raise RuntimeError, err
                        
        if response['status'] is not None:
            self.jobRequest.processResponse(response)
