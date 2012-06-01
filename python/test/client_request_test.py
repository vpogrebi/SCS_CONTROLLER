'''
Created on Aug 14, 2009

@author: valeriypogrebitskiy
'''
import sys
import client
import test_lib
import client_request
import twisted_logger
import simplejson as json

from deferred_lib import sleep
from twisted.trial import unittest
from twisted.python import log, failure
from twisted.protocols.basic import LineReceiver
from twisted.internet import defer, reactor, protocol, task

client_request.scheduleChecks = False

#config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_localhost.cfg"
config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
params = test_lib.getConfig(config_file)
synchdb = test_lib.getSynchDB(params)
db = test_lib.getTwistedMySQLdb(params)

log.startLogging(sys.stdout)

clientManager = client.SCSClientManager(params['log_dir'])
testClientName = None

failFlag = False
processRequest = False

class ServerProtocol(LineReceiver):
    logPrefix = "TEST SERVER"
    dataRcvdDeferred = None
    statusSentDeferred = None
    
    def _jobSuccess(self, nothing, data):
        data = eval(data)
        response = {'type': 'RESPONSE', 'scs_jobid': data['scs_jobid'], 'status': 0, 'err_msg': '', 'result_set': data['request']}
        twisted_logger.writeLog(self.logPrefix, None, "Sending job success response: %s" % response)
        self.sendLine(json.dumps(response))
        
    def _jobFailure(self, nothing, data):
        data = eval(data)
        response = {'type': 'RESPONSE', 'scs_jobid': data['scs_jobid'], 'status': 1, 'err_msg': 'JOB STEP FAILED !!!'}
        twisted_logger.writeLog(self.logPrefix, None, "Sending job failure response: %s" % response)
        self.sendLine(json.dumps(response))
        
    def _jobStatusRunning(self, nothing, data):
        if self.transport.connected:
            data = eval(data)
#            response = {'type': 'STATUS', 'scs_jobid': data['scs_jobid'], 'status': None, 'err_msg': ''}
            response = {'type': 'STATUS', 'status': None, 'err_msg': ''}
            twisted_logger.writeLog(self.logPrefix, None, "Sending job status response (job is running): %s" % response)
            self.sendLine(json.dumps(response))
            if self.statusSentDeferred:
                if not self.statusSentDeferred.called:
                    self.statusSentDeferred.callback(response)
        
    def _jobStatusFailure(self, nothing, data):
        if self.transport.connected:
            data = eval(data)
#            response = {'type': 'STATUS', 'scs_jobid': data['scs_jobid'], 'status': 1, 'err_msg': 'JOB STEP FAILED !!!'}
            response = {'type': 'STATUS', 'status': 1, 'err_msg': 'JOB STEP FAILED !!!'}
            twisted_logger.writeLog(self.logPrefix, None, "Sending job status response (job has failed): %s" % response)
            self.sendLine(json.dumps(response))
            if self.statusSentDeferred:
                if not self.statusSentDeferred.called:
                    self.statusSentDeferred.callback(response)
        
    def lineReceived(self, data):
        dict_data = json.loads(data)
        print "DICT DATA: %s" % dict_data
        if dict_data['type'] == 'REQUEST':
            twisted_logger.writeLog(self.logPrefix, None, "Server received request: %s" % data)
            if self.dataRcvdDeferred:
                if not self.dataRcvdDeferred.called:
                    self.dataRcvdDeferred.callback(data)
            if processRequest:
                if not failFlag:
                    twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job on the server that succeeds...")
                    # Imitate long running job on the server, and call back deferred
                    sleep(None, 3).addCallback(self._jobSuccess, data)
                else:
                    twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job on the server that fails...")
                    # Imitate long running job on the server, and call back deferred
                    sleep(None, 3).addCallback(self._jobFailure, data)
        elif dict_data['type'] == 'STATUS':
            if self.transport.connected:
                twisted_logger.writeLog(self.logPrefix, None, "Received job STATUS request...")
                if not failFlag:
                    # Imitate long running job on the server, and call back deferred
                    sleep(None, 3).addCallback(self._jobStatusRunning, data)
                else:
                    # Imitate long running job on the server, and call back deferred
                    sleep(None, 3).addCallback(self._jobFailure, data)
            
            
class JobRequestTest(unittest.TestCase):
    def _startServerAndClient(self, nothing):
        global testClientName
        "Start servers and clents"
        connDeferreds = []
        testClientName = clientManager.clientInfo.keys()[0]        
        port = clientManager.clientInfo[testClientName]['port']
        # Start server
        self._startServer(port)
        # Start client. Since clientManager.start() returns deferred - return that deferred
        return self._startClientService(testClientName)

    def _startServer(self, port):
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        factory.protocol.dataRcvdDeferred = self.dataReceivedDeferred
        factory.protocol.statusSentDeferred = self.statusSentDeferred
        # Start server
        self.listeningPort = reactor.listenTCP(port, factory)
            
    def _startClientService(self, clientName):
        # Enable client
        clientManager.clientInfo[clientName]['enabled'] = True
        # Start client
        return clientManager.start(clientName).addCallback(self._startClient).addCallback(self._initDone)
        
    def _startClient(self, nothing):
        return clientManager.namedServices[testClientName].startClient()

    def _initDone(self, protocol):
        self.jobRequest = client_request.JobRequest(self.request, defer.Deferred(), protocol)
        protocol.jobRequest = self.jobRequest
        
    def _teardownDone(self, result):
        if isinstance(result, failure.Failure):
            twisted_logger.writeLog(self.logPrefix, logName, "Failure shutting down test server: 5s" % result.getErrorMessage())
        else:
            twisted_logger.writeLog(self.logPrefix, None, "TEST'S tearDown() IS COMPLETE")            

    def setUp(self):
        db.start()

        self.client = None
        self.logPrefix = None
        self.listeningPort = None
        self.jobRequest = None
        unittest.TestCase.timeout = 10
        self.dataReceivedDeferred = defer.Deferred()
        self.statusSentDeferred = defer.Deferred()        
        self.request = {'type': 'REQUEST', 'scs_jobid': 1234, 'request': "I want to run a marathon"}
        return clientManager._loadInfo().addCallback(self._startServerAndClient)
        
    def tearDown(self):
        db.close()
        deferreds = []
        # Stop client
        try:
            deferreds.append(clientManager.stop(testClientName))
        except:
            pass
        # Stop server
        try:
            deferreds.append(self.listeningPort.stopListening())
        except Exception, err:
            print "FAILURE STOPPING TEST SERVER: %s" % str(err)

        return defer.DeferredList(deferreds).addBoth(self._teardownDone)
                
    def test__init__(self):
        "Test that JobRequest.__init__() correctly initializes JobRequest instance"
        self.assertNotEquals(self.jobRequest.deferred, None)
        self.assertEquals(self.jobRequest.request, self.request)
        self.assertEquals(self.jobRequest.scs_jobid, self.request['scs_jobid'])
        self.assertNotEquals(self.jobRequest.statusRequest, None)
        
    def test__checkRequest_FAILURE_SCS_JOBID_MISSING(self):
        "Test that JobRequest._checkRequest() raises exception when job request does not have 'scs_jobid' data"
        testRequest = {'request': "TEST REQUEST"}
        try:
            self.jobRequest._checkRequest(testRequest)
        except RuntimeError, err:
            expect_err = "request does not have 'scs_jobid' data"
            self.assertEquals(expect_err, str(err))
        else:
            err_msg = "JobRequest._checkRequest() does not raise exception when job request does not have 'scs_jobid' data"
            raise self.failureException, err_msg

    def test__checkRequest_FAILURE_REQUEST_MISSING(self):
        "Test that JobRequest._checkRequest() raises exception when job request does not have 'request' data"
        testRequest = {'scs_jobid': 1234}
        try:
            self.jobRequest._checkRequest(testRequest)
        except RuntimeError, err:
            expect_err = "request does not have 'request' data"
            self.assertEquals(expect_err, str(err))
        else:
            err_msg = "JobRequest._checkRequest() does not raise exception when job request does not have 'request' data"
            raise self.failureException, err_msg
        
    def test_JobRequest_processRequest_SENDS_REQUEST(self):
        "Test that JobRequest.processRequest() sends job request to external server"
        global processRequest
        self.logPrefix = "test_JobRequest_processRequest_SENDS_REQUEST"
        
        def checkResults(data):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            data = eval(data)
            self.assertEquals(data['type'], 'REQUEST')
#            self.assertEquals(data['scs_jobid'], self.request['scs_jobid'])
            self.assertEquals(data['request'], self.request['request'])
            self.assertEquals(self.jobRequest.status, None)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We do not care about waiting for a job completion - just want to know that server receives job request
        processRequest = False
        self.dataReceivedDeferred.called = False
        self.dataReceivedDeferred.addCallback(checkResults)
        self.jobRequest.processRequest()
        return self.dataReceivedDeferred
    
    def test_JobRequest_processResponse_JOB_SUCCESS(self):
        "Test that JobRequest.processResponse() correctly processes server's job success response"
        global processRequest, failFlag
        self.logPrefix = "test_JobRequest_processResponse_JOB_SUCCESS"
        
        def checkResults(data):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(data, self.request['request'])
            self.assertEquals(self.jobRequest.status, 'SUCCESS')
            self.assertEquals(self.jobRequest.request, self.request)
            self.assertEquals(self.jobRequest.response, self.request['request'])
            # Check that JobRequest entity has correctly stopped (_stop() was executed)
            self.assertEquals(self.jobRequest.stopped, True, "self.jobRequest.stopped is False")
            self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), False, "self.jobRequest has 'statusRequest' attribute")
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We want to wait for a job completion event
        processRequest = True
        failFlag = False
        self.assertNotEquals(self.jobRequest.statusRequest, None)
        self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), True)
        self.assertEquals(hasattr(self.jobRequest, 'deferred'), True)

        self.assertNotEquals(self.jobRequest.statusRequest, None)
        deferred = defer.Deferred().addCallback(checkResults)
        self.jobRequest.deferred = deferred
        self.jobRequest.processRequest()
        return deferred

    def test_JobRequest_processResponse_JOB_FAILURE(self):
        "Test that JobRequest.processResponse() correctly processes server's job failure response"
        global processRequest, failFlag
        self.logPrefix = "test_JobRequest_processResponse_JOB_FAILURE"
        
        def checkResults(fail):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            expect_errmsg = 'JOB STEP FAILED !!!'
            self.assertEquals(isinstance(fail, failure.Failure), True)
            self.assertEquals(fail.getErrorMessage(), expect_errmsg)
            self.assertEquals(self.jobRequest.status, 'FAILURE')
            self.assertEquals(self.jobRequest.error, expect_errmsg)
            self.assertEquals(self.jobRequest.request, self.request)
            self.assertEquals(self.jobRequest.response, None)
            # Check that JobRequest entity has correctly stopped (_stop() was executed)
            self.assertEquals(self.jobRequest.stopped, True, "self.jobRequest.stopped is False")
            self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), False, "self.jobRequest has 'statusRequest' attribute")
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We want to wait for a job completion event
        processRequest = True
        failFlag = True
        self.assertNotEquals(self.jobRequest.statusRequest, None)
        self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), True)
        self.assertEquals(hasattr(self.jobRequest, 'deferred'), True)

        deferred = defer.Deferred().addErrback(checkResults)
        self.jobRequest.deferred = deferred
        self.jobRequest.processRequest()
        return deferred

    def test_JobRequest_processResponse_JOB_SUCCESS_DEFERRED_CANCELED(self):
        "Test that JobRequest.processResponse() processes job success when job step deferred's callback is canceled"
        global processRequest, failFlag
        self.logPrefix = "test_JobRequest_processResponse_JOB_SUCCESS_DEFERRED_CANCELED"
        
        def checkResults(data, deferredCanceled):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(data, None)
            self.assertEquals(deferredCanceled, True)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We want to wait for a job completion event
        processRequest = True
        failFlag = False
        self.assertNotEquals(self.jobRequest.statusRequest, None)
        self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), True)
        self.assertEquals(hasattr(self.jobRequest, 'deferred'), True)

        self.assertNotEquals(self.jobRequest.statusRequest, None)
        deferred = defer.Deferred().addCallback(checkResults, False)
        self.jobRequest.deferred = deferred
        
        # Delete job step's deferred
        del self.jobRequest.deferred
        self.jobRequest.processRequest()
        deferred1 = sleep(None, 5).addCallback(checkResults, True)
        return deferred1

    def test_JobRequest_processResponse_JOB_FAILURE_DEFERRED_CANCELED(self):
        "Test that JobRequest.processResponse() processes job failure when job step deferred's callback is canceled"
        global processRequest, failFlag
        self.logPrefix = "test_JobRequest_processResponse_JOB_FAILURE"
        
        def checkResults(data, deferredCanceled):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(data, None)
            self.assertEquals(deferredCanceled, True)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We want to wait for a job completion event
        processRequest = True
        failFlag = True
        self.assertNotEquals(self.jobRequest.statusRequest, None)
        self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), True)
        self.assertEquals(hasattr(self.jobRequest, 'deferred'), True)

        deferred = defer.Deferred().addErrback(checkResults, False)
        self.jobRequest.deferred = deferred

        # Delete job step's deferred
        del self.jobRequest.deferred
        self.jobRequest.processRequest()
        deferred1 = sleep(None, 5).addCallback(checkResults, True)
        return deferred1

    def test_JobStatusRequest_processRequest_SENDS_REQUEST(self):
        "Test that JobStatusRequest.processRequest() sends job status request to external server"
        global processRequest, failFlag
        self.logPrefix = "test_JobStatusRequest_processRequest_SENDS_REQUEST"
        
        def checkResults(data):
            # Reset deferrred
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(data['type'], 'STATUS')
            self.assertEquals(self.jobRequest.status, None)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We do not care about waiting for a job completion - just want to know that server receives job request
        processRequest = False
        failFlag = False
        
        self.statusSentDeferred.addCallback(checkResults)
        
        self.statusSentDeferred.called = False
        statusRequest = self.jobRequest.statusRequest
        # Check that status polling is NOT scheduled
        self.assertEquals(statusRequest.loop, None)
        # Initialize job status polling checks for this test
        statusRequest._startStatusChecks(now = True)        
        # Check that status polling is scheduled
        self.assertNotEquals(statusRequest.loop, None)        
        return self.statusSentDeferred

    def test_JobStatusRequest_processResponse_JOB_SUCCESS(self):
        "Test that JobStatusRequest.processResponse() correctly processes server's SUCCESS job status response"
        global processRequest, failFlag
        self.logPrefix = "test_JobStatusRequest_processResponse_JOB_SUCCESS"
        
        def checkResults(data, response):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(data, self.request['request'])
            self.assertEquals(self.jobRequest.status, 'SUCCESS')
            self.assertEquals(self.jobRequest.request['request'], self.request['request'])
            self.assertEquals(self.jobRequest.response, response['result_set'])
            self.assertEquals(self.jobRequest.error, None)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We want to wait for a job completion
        processRequest = False
        failFlag = False
                
#        response = {'status': 0, 'err_msg': '', 'scs_jobid': 1234, 'type': 'STATUS', 'result_set': self.request['request']}
        response = {'status': 0, 'err_msg': '', 'type': 'STATUS', 'result_set': self.request['request']}
        self.jobRequest.deferred.addCallback(checkResults, response)
        self.jobRequest.statusRequest.processResponse(response)        
        return self.jobRequest.deferred

    def test_JobStatusRequest_processResponse_JOB_FAILURE(self):
        "Test that JobStatusRequest.processResponse() correctly processes server's FAILURE job status response"
        global processRequest, failFlag
        self.logPrefix = "test_JobStatusRequest_processResponse_JOB_FAILURE"
        
        def checkResults(fail):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            expect_errmsg = 'JOB STEP FAILED !!!'
            self.assertEquals(isinstance(fail, failure.Failure), True)
            self.assertEquals(fail.getErrorMessage(), expect_errmsg)
            self.assertEquals(self.jobRequest.status, 'FAILURE')
            self.assertEquals(self.jobRequest.error, expect_errmsg)
            self.assertEquals(self.jobRequest.request, self.request)
            self.assertEquals(self.jobRequest.response, None)
            # Check that JobRequest entity has correctly stopped (_stop() was executed)
            self.assertEquals(self.jobRequest.stopped, True, "self.jobRequest.stopped is False")
            self.assertEquals(hasattr(self.jobRequest, 'statusRequest'), False, "self.jobRequest has 'statusRequest' attribute")
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # We want to wait for a job completion
        processRequest = False
        failFlag = False
                
        response = {'status': 1, 'err_msg': 'JOB STEP FAILED !!!', 'scs_jobid': 1234, 'type': 'STATUS', 'result_set': None}
        self.jobRequest.deferred.addErrback(checkResults)
        self.jobRequest.statusRequest.processResponse(response)        
        return self.jobRequest.deferred
    
if __name__=="__main__":
    unittest.pyunit.main()
