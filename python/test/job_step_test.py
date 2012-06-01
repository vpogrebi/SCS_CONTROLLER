'''
Created on Jul 20, 2009

@author: valeriypogrebitskiy
'''
import sys
import client
import test_lib
import job_step
import workflow
import client_request
import twisted_logger
import simplejson as json

from twisted.internet import defer
from twisted.trial import unittest
from twisted.python import log, failure
from deferred_lib import sleep, deferred
from twisted.protocols.basic import LineReceiver
from twisted.internet import defer, reactor, protocol

config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
params = test_lib.getConfig(config_file)
synchdb = test_lib.getSynchDB(params)
db = test_lib.getTwistedMySQLdb(params)

testWFName = 'DORTHY_WORKFLOW'
testJobID = 99999

# Set client_request.scheduleChecks to False - in order to avoid scheduling job status checks when client instantiates JobRequest
client_request.scheduleChecks = False
job_step.client.client_request.scheduleChecks = False
# Reset workflow.autoDiscovery to False - so Workflow._checkEnabled() does not interfere with test execution
workflow.autoDiscovery = False
workflow.useDB = False

workflowManager = workflow.WorkflowManager(params['log_dir'])
clientManager = client.SCSClientManager(params['log_dir'])

failFlag = False
log.startLogging(sys.stdout)

class ServerProtocol(LineReceiver):
    connDeferred = None
    disconnDeferred = None
    dataRcvdDeferred = None
    logPrefix = "TEST SERVER"
    
    def _jobSuccess(self, nothing, data):
        response = {'type': 'RESPONSE', 'scs_jobid': data['scs_jobid'], 'status': 0, 'err_msg': ''}
        self.sendLine(json.dumps(response))
        
    def _jobFailure(self, nothing, data):
#        data = eval(data)
        response = {'type': 'RESPONSE', 'scs_jobid': data['scs_jobid'], 'status': 1, 'err_msg': 'JOB STEP FAILED !!!'}
        self.sendLine(json.dumps(response))
        
    def connectionMade(self):
        protocol.Protocol.connectionMade(self) 
        if self.connDeferred:    
            self.connDeferred.callback("connected")

    def connectionLost(self, reason):
        protocol.Protocol.connectionLost(self, reason)
        if self.disconnDeferred:
            self.disconnDeferred.callback("disconnected")
            
    def lineReceived(self, data):
        data = json.loads(data)
        twisted_logger.writeLog(self.logPrefix, None, "Server received request: %s" % data)
        if not failFlag:
            twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job on the server that succeeds...")
            # Imitate long running job on the server, and call back deferred
            sleep(None, 3).addCallback(self._jobSuccess, data)
        else:
            twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job on the server that fails...")
            # Imitate long running job on the server, and call back deferred
            sleep(None, 3).addCallback(self._jobFailure, data)
            
class JobStepTest(unittest.TestCase):
    def __checkJobStepResults(self, failure, status):
        "Check that given self.js.status is set to correct value after certain JobStep operation"
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")

        if failure is not None:
            error = failure.getErrorMessage()
            failure.trap(RuntimeError)
            print "ERROR: %s" % error
        else:
            error = None
            
        query = "select status, text_input, error, start_time, end_time from scs.job_step " \
                "where job_id = %d and step_id = %d" % (self.js.jobID, self.js.stepID) 
        res = synchdb.query(query)
        db_status, text_input, db_error, start_time, end_time = res[0]

        self.assertEquals(str(self.js.input), text_input, "<scs.job_step> text_input ('%s') not equals to expected input ('%s')" % (text_input, str(self.js.input)))
        self.assertEquals(error, db_error, "<scs.job_step> error ('%s') not equals to expected error ('%s')" % (db_error, error))
        self.assertEquals(status, db_status, "<scs.job_step> status ('%s') not equals to expected status ('%s')" % (db_status, status))
        self.assertEquals(self.js.status, status, "<js.status> ('%s') not equals to expected status ('%s')" % (self.js.status, status))
        if self.js.status != 'RUNNING':
            self.assertNotEquals(end_time, None)
            
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        

    def _startTestServer(self, status = None):
        # Initialize and start test server
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        factory.protocol.dataRcvdDeferred = defer.Deferred()
        if status:
            factory.protocol.dataRcvdDeferred.addCallback(self.__checkJobStepResults, status)
        self.listeningPort = reactor.listenTCP(testPort, factory)
    
    def _startTestClient(self):
        # Initialize and start test client
        clientManager.clientInfo[testClientName]['enabled'] = True
        return clientManager.start(testClientName)

    def _tearDownComplete(self, result):
        failFlag = False
        
        for (success, value) in result:
            if not success:
                twisted_logger.writeLog(self.logPrefix, None, "tearDown() failure: %s" % value.getErrorMessage())
                failFlag = True
                break
            
        if failFlag is False:
            twisted_logger.writeLog(self.logPrefix, None, "tearDown() success")
            
    def _startWorkflow(self, nothing):
        global testWorkflow, testStepInfo, testClientName, testPort
        
        # Start workflow
        workflowManager.workflowInfo[testWFName]['enabled'] = True
        
        # Obtain test workflow step info from scs.workflow_step table
        testStepInfo = workflowManager.workflowInfo[testWFName]['steps'][-1]
        testClientName = testStepInfo['clientName']
        testPort = clientManager.clientInfo[testClientName]['port']

        workflowManager.start(testWFName)
        testWorkflow = workflowManager.getResource(testWFName)
        self.js = job_step.JobStep(testWorkflow, testJobID, testStepInfo)
#        self._startTestServer()
        return self.js.init()
        
    def setUp(self):
        global failFlag
        db.start()
        deferreds = []

        failFlag = False
        self.logPrefix = None
        self.listeningPort = None
        unittest.TestCase.timeout = 10
        deferreds.append(clientManager._loadInfo())
        deferreds.append(workflowManager._loadInfo())
        return defer.DeferredList(deferreds).addCallback(self._startWorkflow)

    def tearDown(self):
        stmt = "delete from scs.job_step where job_id = %d and step_id = %d" % (self.js.jobID, self.js.stepID)
        synchdb.execute(stmt)
        stmt = "delete from scs.job where job_id = %d" % self.js.jobID
        synchdb.execute(stmt)
        deferreds = []
        db.close()

        try:
            deferreds.append(clientManager.stopService())
        except Exception, err:
            print str(err)
            pass
            
        workflowManager.stop(testWFName)
        
        if self.listeningPort:
            deferreds.append(self.listeningPort.stopListening())
            
        return defer.DeferredList(deferreds).addBoth(self._tearDownComplete)
    
    def test__init__(self):
        "Test that JobStep.__init__() succeeds"
        self.logPrefix = "test__init__"
        self.assertEquals(self.js.db, db)
        self.assertEquals(self.js.input, None)
        self.assertEquals(self.js.output, None)
        self.assertEquals(self.js.status, 'NEW')
        self.assertEquals(self.js.jobID, testJobID)
        self.assertEquals(self.js.workflow, testWorkflow)
        self.assertEquals(self.js.stepID, testStepInfo['stepID'])
        self.assertEquals(self.js.client, testStepInfo['clientName'])
        self.assertEquals(self.js.stepNo, testStepInfo['stepNo'])
        self.assertEquals(self.js.lastStep, testStepInfo['outFlag'])
        self.assertEquals(self.js.inputSource, testStepInfo['inputSrc'])
        self.assertEquals(True, isinstance(self.js.deferred, defer.Deferred))
       
    def test_run_FAILURE(self):
        "Test that JobStep.run() raises exception when SCSClientManager.sendRequest() fails sending request to the server"
        self.logPrefix = "test_run_FAILURE"
        self.assertEquals(self.js.status, 'NEW')        
        testRequest = {'scs_jobid': testJobID, 'request': "I want to run a marathon"}
        self.js.deferred = None
        twisted_logger.writeLog(self.logPrefix, None, "Test client has not started... Trying to execute JobStep.run()...")
        # Test client (self.client) is not running... SCSJobStep.run() should fail
        return self.js.run(str(testRequest)).addErrback(self.__checkJobStepResults, 'FAILURE')

    def test_run_SUCCESS(self):
        "Test that JobStep.run() successfully initiates job step"
        self.logPrefix = "test_run_SUCCESS"
        
        def runJobStep(nothing):
            global failFlag
            twisted_logger.writeLog(self.logPrefix, None, "Test client is connected to server...")
            testRequest = {'scs_jobid': testJobID, 'request': "I want to run a marathon"}
            self.js.deferred.addErrback(self.__checkJobStepResults, 'SUCCESS')
            # Set <failFlag> to True - to imitate job step failure on the server
            failFlag = False
            twisted_logger.writeLog(self.logPrefix, None, "Executing JobStep.run()...")            
            return self.js.run(testRequest).addCallback(self.__checkJobStepResults, 'RUNNING')
            
        self.assertEquals(self.js.status, 'NEW')        
        # Start test server
        self._startTestServer()         
        # Start test client and use deferred to perform the test
        return self._startTestClient().addCallback(runJobStep)
        
    def test_successHandler(self):
        "Test that JobStep.successHandler() correctly handles job step completion event"
        self.logPrefix = "test_successHandler"
        
        def runJobStep(nothing):
            global failFlag
            twisted_logger.writeLog(self.logPrefix, None, "Test client is connected to server...")
            testRequest = {'scs_jobid': testJobID, 'request': "I want to run a marathon"}
            self.js.deferred.addErrback(self.__checkJobStepResults, 'SUCCESS')
            # Set <failFlag> to True - to imitate job step failure on the server
            failFlag = False
            twisted_logger.writeLog(self.logPrefix, None, "Executing JobStep.run()...")            
            self.js.run(testRequest)
            # Wait for JobStep.successHandler() to execute
            return self.js.deferred
            
        self.assertEquals(self.js.status, 'NEW')        
        # Start test server
        self._startTestServer()
        # Start test client and use deferred to perform the test
        return self._startTestClient().addCallback(runJobStep)

    def test_failureHandler(self):
        "Test that JobStep.failureHandler() correctly handles job step failure event"
        self.logPrefix = "test_failureHandler"
        
        def runJobStep(nothing):
            global failFlag
            twisted_logger.writeLog(self.logPrefix, None, "Test client is connected to server...")
            testRequest = {'scs_jobid': testJobID, 'request': "I want to run a marathon"}
            self.js.deferred.addErrback(self.__checkJobStepResults, 'FAILURE')
            # Set <failFlag> to True - to imitate job step failure on the server
            failFlag = True
            twisted_logger.writeLog(self.logPrefix, None, "Executing JobStep.run()...")            
            self.js.run(testRequest)
            # Wait for JobStep.successHandler() to execute
            return self.js.deferred
            
        self.assertEquals(self.js.status, 'NEW')        
        # Start test server
        self._startTestServer()
        # Start test client and use deferred to perform the test
        return self._startTestClient().addCallback(runJobStep)

if __name__=="__main__":
    unittest.pyunit.main()
