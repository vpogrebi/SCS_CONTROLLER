'''
Created on Jul 29, 2009

@author: valeriypogrebitskiy
'''
import sys
import job
import urllib
import server
import client
import workflow
import test_lib
import deferred_lib
import twisted_logger
import simplejson as json

from deferred_lib import sleep
from twisted.trial import unittest
from twisted.python import log, failure
from twisted.protocols.basic import LineReceiver
from twisted.internet import defer, reactor, protocol

# Start logging
log.startLogging(sys.stdout)

config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
params = test_lib.getConfig(config_file)
synchdb = test_lib.getSynchDB(params)
db = test_lib.getTwistedMySQLdb(params)

server.workflow.useDB = False
server.workflow.autoDiscovery = False
client.scheduleChecks = True
client.client_request.scheduleChecks = False

clientManager = client.SCSClientManager(None)
serverManager = server.SCSServerManager(params['log_dir'])
workflowManager = workflow.WorkflowManager(None)

testServerName = 'DORTHY_SERVER'
testClientName = 'EES_CLIENT'
testWorkflowName = 'DORTHY_WORKFLOW'

class SCSServerManagerTest(unittest.TestCase):
    def _setupDone(self, nothing):
        # Enable test server, client and workflow (in case they are disabled) 
        serverManager.serverInfo[testServerName]['enabled'] = True
        
    def setUp(self):
        db.start()
        self.logPrefix = None
        unittest.TestCase.timeout = 10
        deferreds = []
        deferreds.append(serverManager._loadInfo())
        deferreds.append(workflowManager._loadInfo())
        return defer.DeferredList(deferreds).addCallback(self._setupDone)

    def tearDown(self):
        db.close()
        return serverManager.stopService()
        
    def test__init__(self):
        "Test that SCSServerManager.__init__() correctly loads server info"
        self.logPrefix = "SCSServerManagerTest.test__init__"
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(serverManager.namedServices, {})
        
        query = "select server_name, wf_name, port, protocol, max_connections, enabled from scs.scs_server"
        res = synchdb.query(query)
        
        self.assertEquals(len(res), len(serverManager.serverInfo.keys()))
        for serverName in serverManager.serverInfo.keys():
            for rec in res:
                if serverName == res[0]:
                    self.assertEquals(serverManager.serverInfo[serverName]['workflow'], res[1])
                    self.assertEquals(serverManager.serverInfo[serverName]['port'], res[2])
                    self.assertEquals(serverManager.serverInfo[serverName]['protocol'], res[3])
                    self.assertEquals(serverManager.serverInfo[serverName]['max_connections'], res[4])
                    self.assertEquals(serverManager.serverInfo[serverName]['enabled'], res[5])
                    break
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")        
    
    def test_start_SUCCESS(self):
        "Test that SCSServerManager.start() successfully starts given server"
        self.logPrefix = "SCSServerManagerTest.test_start_SUCCESS"

        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(serverManager.running == 1, True)
            self.assertEquals(serverManager.namedServices.has_key(testServerName), True)
            self.assertEquals(serverManager.namedServices[testServerName].running, True)        
            self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        return serverManager.start(testServerName).addCallback(checkResults)
    
    def test_start_FAILURE_SERVER_RUNNING(self):
        "Test that SCSServerManager.start() raises exception when starting server that's already running"
        self.logPrefix = "SCSServerManagerTest.test_start_FAILURE_SERVER_RUNNING"

        def startAgain(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking that '%s' server is online..." % testServerName)
            self.assertEquals(serverManager.namedServices.has_key(testServerName), True)
            self.assertEquals(serverManager.namedServices[testServerName].running, True)
            self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
            twisted_logger.writeLog(self.logPrefix, None, "Server is online. Attempting to start server again...")            
            try:
                serverManager.start(testServerName)
            except RuntimeError, err:
                twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
                expect_err = "Server is already running on port #%d" % serverManager.serverInfo[testServerName]['port']
                self.assertEquals(str(err).find(expect_err) >= 0, True)
                twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        return serverManager.start(testServerName).addCallback(startAgain)
        
    def test_start_RESTARTS_STOPPED_SERVER(self):
        "Test that SCSServerManager.start() restarts server that was previously stopped"
        self.logPrefix = "SCSServerManagerTest.test_start_RESTARTS_STOPPED_SERVER"
        
        def restartService(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Verifying that '%s' service has stopped..." % testServerName)
            self.assertEquals(serverManager.running, True)
            # Verify that server is deleted from ServerManager.services list and ServerManager.namedServices dictionary
            self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
            twisted_logger.writeLog(self.logPrefix, None, "Service has stopped. Restarting the service...")            
            # Restart the server
            return serverManager.start(testServerName).addCallback(checkResults)

        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            # Verify that server is listening on a port again
            self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")            
            
        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        serverManager.start(testServerName)
        self.assertEquals(serverManager.namedServices.has_key(testServerName), True)
        self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
        try:
            serverManager.start(testServerName)
        except RuntimeError, err:
            expect_err = "Server is already running on port #%d" % serverManager.serverInfo[testServerName]['port']
            self.assertEquals(str(err).find(expect_err) >= 0, True)
        else:
            err_msg = "ServerManager.start() does not raise exception when starting server that's already running"
            raise self.failureException, err_msg
        
        # Verify that serverManager service itself is running
        self.assertEquals(serverManager.running == 1, True) 
        return defer.maybeDeferred(serverManager.stop, testServerName).addCallback(restartService)
    
    def test_start_FAILURE_SERVER_DISABLED(self):
        "Test that SCSServerManager.start() raises exception when starting disabled server"
        self.logPrefix = "SCSServerManagerTest.test_start_FAILURE_SERVER_DISABLED"
        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        serverManager.serverInfo[testServerName]['enabled'] = False
        try:
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            serverManager.start(testServerName)
            err_msg = "ServerManager.start() does not raise exception when starting disabled server"
            raise self.failureException, err_msg
        except RuntimeError, err:
            expect_err = "Server is disabled"
            self.assertEquals(str(err).find(expect_err) >= 0, True)        
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        finally:
            serverManager.serverInfo[testServerName]['enabled'] = True
            
    def test_stop(self):
        "Test that SCSServerManager.stop() successfully stops given server"
        self.logPrefix = "SCSServerManagerTest.test_stop"
        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            # Verify that server is deleted from Servermanager.namedServices dictionary
            self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        serverManager.start(testServerName)
        self.assertEquals(serverManager.namedServices.has_key(testServerName), True)
        self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
        deferred = serverManager.stop(testServerName)
        if deferred:
            return deferred.addCallback(checkResults)
        else:
            checkResults(None)    
    
    def test_startUp(self):
        "Test that SCSServerManager.startup() successfully starts all enabled servers"
        self.logPrefix = "SCSServerManagerTest.test_startUp"
        origEnabled = {}
        for servername in serverManager.serverInfo.keys():
            origEnabled[servername] = serverManager.serverInfo[servername]['enabled']
            if not serverManager.serverInfo[servername]['enabled']:
                serverManager.serverInfo[servername]['enabled'] = True
                
        serverManager.startUp()
        
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        for servername in serverManager.serverInfo.keys():
            self.assertEquals(serverManager.namedServices.has_key(servername), True)
            self.assertEquals(serverManager.namedServices[servername].running == 1, True)
            self.assertEquals(serverManager.namedServices[servername].listeningPort.connected, True)
            serverManager.serverInfo[servername]['enabled'] = origEnabled[servername]
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        
        return serverManager.shutDown()

    def test_shutDown(self):
        "Test that SCSServerManager.shutDown() stops all running servers"
        self.logPrefix = "SCSServerManagerTest.test_shutDown"

        def shutDown(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking that all services are running...")
            self.assertEquals(serverManager.running == 1, True)
            for servername in serverManager.serverInfo.keys():
                self.assertEquals(serverManager.namedServices.has_key(servername), True)
                self.assertEquals(serverManager.namedServices[servername].running == 1, True)
                self.assertEquals(serverManager.namedServices[servername].listeningPort.connected, True)
                serverManager.serverInfo[servername]['enabled'] = origEnabled[servername]
            twisted_logger.writeLog(self.logPrefix, None, "All services are running. Executing shutDown()...")            
            return serverManager.shutDown().addCallback(checkResults)
            
        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            for servername in serverManager.serverInfo.keys():
                self.assertEquals(serverManager.namedServices.has_key(servername), False)
            self.assertEquals(serverManager.running == 1, False)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
                    
        origEnabled = {}
        for servername in serverManager.serverInfo.keys():
            origEnabled[servername] = serverManager.serverInfo[servername]['enabled']
            if not serverManager.serverInfo[servername]['enabled']:
                serverManager.serverInfo[servername]['enabled'] = True
                
        return serverManager.startUp().addCallback(shutDown)
    
    def test_getResource(self):
        "Test that SCSServerManager.getResource() returns reference to a listeningPort corresponding to a given server"
        self.logPrefix = "SCSServerManagerTest.test_getResource"
        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        serverManager.start(testServerName)
        self.assertEquals(serverManager.namedServices.has_key(testServerName), True)
        self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(serverManager.getResource(testServerName), serverManager.namedServices[testServerName].listeningPort)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_setWorkflow(self):
        "Test that SCSServerManager.setWorkflow() sets server's workflow"
        self.logPrefix = "SCSServerManagerTest.test_setWorkflow"
        self.assertEquals(serverManager.namedServices.has_key(testServerName), False)
        serverManager.start(testServerName)
        self.assertEquals(serverManager.namedServices.has_key(testServerName), True)
        self.assertEquals(serverManager.namedServices[testServerName].listeningPort.connected, True)
        # Verify that after server's initialization workflow is not set 
        self.assertEquals(serverManager.namedServices[testServerName].listeningPort.factory.workflow, None)

        # Start test workflow
        workflowManager.start(testWorkflowName)
        # Set server's workflow
        serverManager.setWorkflow(testServerName)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        # Verify that workflow is set
        self.assertEquals(serverManager.namedServices[testServerName].listeningPort.factory.workflow, workflowManager.getResource(testWorkflowName))
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        workflowManager.stop(testWorkflowName)
        serverManager.getResource(testServerName).factory.workflow = None        

class _SCSServerHTTPRequestTest(unittest.TestCase):
    def _setupDone(self, nothing):
        # Enable test server, client and workflow (in case they are disabled) 
        serverManager.serverInfo[testServerName]['enabled'] = True
        clientManager.clientInfo[testClientName]['enabled'] = True
        workflowManager.workflowInfo[testWorkflowName]['enabled'] = True

        # Enable workflow step corresponding to test client
        for step in workflowManager.workflowInfo[testWorkflowName]['steps']:
            if step['clientName'] == testClientName:
                step['enabled'] = True
                break
            
#        if self.serverFactory.protocols == []:
#            # Server has not yet completed accepting client's connection
#            # We have to wait for that to complete
#            return sleep(None, .1).addCallback(self._setupDone)
#        
#        # Client connection completed
#        self.serverProtocol = self.serverFactory.protocols[0]

        # Start test workflow
        workflowManager.start(testWorkflowName)
        # Imitate workflow being 'online'
        workflowManager.getResource(testWorkflowName).online = True
        # Set server's workflow attribute
        serverManager.setWorkflow(testServerName)
        self.httpRequest = server._SCSServerHTTPRequest(server._SCSServerProtocol(), 0)        
    
    def _startTestServer(self, nothing):
        global testServerName
        deferreds = []
        testServerName = [serverName for serverName in serverManager.serverInfo.keys() if serverManager.serverInfo[serverName]['workflow'] == testWorkflowName][0]
        # Start test server
        deferreds.append(serverManager.start(testServerName))        
        self.serverFactory = serverManager.getResource(testServerName).factory
        # Reset test client's host and port to the ones used by test server
        clientManager.clientInfo[testClientName]['host'] = 'localhost'
        clientManager.clientInfo[testClientName]['port'] = serverManager.serverInfo[testServerName]['port']
        deferreds.append(clientManager.start(testClientName))
        return defer.DeferredList(deferreds).addCallback(self._setupDone)
                
    def setUp(self):
        db.start()
        deferreds = []

        self.jobID = None
        self.logPrefix = None
        self.httpRequest = None
        self.serverProtocol = None
        unittest.TestCase.timeout = 10
        deferreds.append(clientManager._loadInfo())
        deferreds.append(workflowManager._loadInfo())
        deferreds.append(serverManager._loadInfo())        
        return defer.DeferredList(deferreds).addCallback(self._startTestServer)
        
    def tearDown(self):
        # Cleanup scs.job and scs.job_step tables
        if self.jobID:
            stmt = "delete from scs.job_step where job_id = %d" % self.jobID
            synchdb.execute(stmt)                
            stmt = "delete from scs.job where job_id = %d" % self.jobID
            synchdb.execute(stmt)

        db.close()

        deferreds = []
        try:
            deferreds.append(clientManager.stopService())
        except:
            pass
        
        try:
            deferreds.append(workflowManager.stopService())
        except:
            pass
        
        try:
            # Stop server and wait for deferred's callback
            deferreds.append(serverManager.stopService())
        except:
            pass
        
        return defer.DeferredList(deferreds)
                
    def test__init__(self):
        "Test that JobRequest.__init__() correctly initializes JobRequest instance"
        self.logPrefix = "test__init__"
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(self.httpRequest.job, None)
        self.assertEquals(self.httpRequest.status, None)
        self.assertEquals(self.httpRequest.response, None)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test__checkRequest_BAD_REQUEST(self):
        "Test that _SCSServerHTTPRequest._checkRequest() raises exception when 'REQUEST' request does not contain 'request' data"
        self.httpRequest.args = {'type': 'REQUEST'}
        try:
            self.httpRequest._checkRequest()
        except RuntimeError, err:
            expect_err = "request data does not specify 'request' data"
            self.assertEquals(str(err).find(expect_err) >= 0, True)
        else:
            err_msg = "'REQUEST' message must contain 'request' data"
            raise self.failureException, err_msg
        
    def test__checkRequest_SUCCESS(self):
        "Test that _SCSServerHTTPRequest._checkRequest() succeeds when valid request is supplied"
        self.httpRequest.args = {'request': ['I want to run a marathon']}
        self.httpRequest._checkRequest()
        
    def test__checkWorkflowStatus_WORKFLOW_DISABLED(self):
        "Test that _SCSServerHTTPRequest._checkWorkflowStatus() raises exception when server's workflow is disabled"
        workflow = self.serverFactory.workflow
        workflow.enabled = False
        self.httpRequest.channel.factory = self.serverFactory
        try:
            self.httpRequest._checkWorkflowStatus()
        except RuntimeError, err:
            expect_err = "'%s' workflow is disabled" % workflow.name
            self.assertEquals(expect_err, str(err))
        else:
            err_msg = "_SCSServerHTTPRequest._checkWorkflowStatus() does not raise exception when server's workflow is disabled"
            raise self.failureException, err_msg
        
    def test__checkWorkflowStatus_WORKFLOW_OFFLINE(self):
        "Test that _SCSServerHTTPRequest._checkWorkflowStatus() raises exception when server's workflow is offline"
        workflow = self.serverFactory.workflow
        workflow.online = False
        self.httpRequest.channel.factory = self.serverFactory
        try:
            self.httpRequest._checkWorkflowStatus()
        except RuntimeError, err:
            expect_err = "'%s' workflow is offline" % workflow.name
            self.assertEquals(expect_err, str(err))
        else:
            err_msg = "_SCSServerHTTPRequest._checkWorkflowStatus() does not raise exception when server's workflow is offline"
            raise self.failureException, err_msg

    """    
    def test_process_STARTS_JOB(self):
        "Test that _SCSServerHTTPRequest.process() starts job (job.Job instance)"
        global processRequest
        self.logPrefix = "test_process_STARTS_JOB"
        
        def checkResults(result):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            if isinstance(result, failure.Failure):
                result.trap(Exception)
                raise self.failureException, "Test failed: %s" % result.getErrorMessage()
            else:
                self.assertNotEquals(self.httpRequest.job, None)
                self.jobID = self.httpRequest.job.jobID
                self.assertEquals(self.httpRequest.job.status, 'RUNNING')
                self.assertEquals(self.httpRequest.job.error, None)
                self.assertEquals(self.httpRequest.job.output, None)
                self.assertEquals(self.httpRequest.job.input, self.httpRequest.args['request'][0])
                twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # Set self.httpRequest.args dictionary for testing
        self.httpRequest.args = {'request': ['I want to run a marathon']}
        # Set test workflow's 'online' and 'enabled' attributes to True - to avoid exception from being raised by _checkWorkflowStatus()
        self.serverFactory.workflow.online = True
        self.serverFactory.workflow.enabled = True        
        # Set self.httpRequest.channel.factory (to simulate live client connection)
        self.httpRequest.channel.factory = self.serverFactory

        self.assertEquals(self.httpRequest.job, None)
        # Start JobRequest.processRequest() and check for its results after deferred (returned by the method) is called back
        return self.httpRequest.process().addBoth(checkResults)    
    """
    
    def test_processResponse_JOB_SUCCESS(self):
        "Test that _SCSServerHTTPRequest.processResponse() correctly processes server's job success response"
        global processRequest, failFlag
        self.logPrefix = "test_processResponse_JOB_SUCCESS"

        def processResponse(nothing):
            self.assertNotEquals(self.httpRequest.job, None)
            self.jobID = self.httpRequest.job.jobID
            self.httpRequest.job.status = 'SUCCESS'
            self.httpRequest.job.input = self.httpRequest.args['request'][0]
            self.httpRequest.job.output = self.httpRequest.job.input
            self.httpRequest.processResponse(None, sendResponse = False)
            
            self.assertEquals(self.httpRequest.job, None)
            jobDict = self.httpRequest.channel.factory.jobInfos[self.jobID]
            self.assertEquals(jobDict['status'], 'SUCCESS')
            self.assertEquals(jobDict['error'], None)
            self.assertEquals(jobDict['input'], self.httpRequest.args['request'][0])
            self.assertEquals(jobDict['output'], self.httpRequest.args['request'][0])        
        
        # Set self.httpRequest.args dictionary for testing
        self.httpRequest.args = {'request': ['I want to run a marathon']}
        # Set self.httpRequest.channel.factory (to simulate live client connection)
        self.httpRequest.channel.factory = self.serverFactory
        # Create new job instance for testing
        self.httpRequest.job = job.Job(self.httpRequest.channel.factory.workflow, self.httpRequest.channel.factory.name)
        return self.httpRequest.job.init().addCallback(processResponse)

    def test_processResponse_JOB_FAILURE(self):
        "Test that _SCSServerHTTPRequest.processResponse() correctly processes server's job failure response"
        global processRequest, failFlag
        self.logPrefix = "test_processResponse_JOB_FAILURE"

        def processResponse(nothing):
            self.assertNotEquals(self.httpRequest.job, None)
            self.jobID = self.httpRequest.job.jobID
            self.httpRequest.job.status = 'FAILURE'
            err_msg = 'job has failed'
            self.httpRequest.job.error = err_msg             
            self.httpRequest.job.input = self.httpRequest.args['request'][0]
            self.httpRequest.processResponse(failure.Failure(err_msg, RuntimeError), sendResponse = False)
            
            self.assertEquals(self.httpRequest.job, None)
            jobDict = self.httpRequest.channel.factory.jobInfos[self.jobID]
            self.assertEquals(jobDict['status'], 'FAILURE')
            self.assertEquals(jobDict['error'], err_msg)
            self.assertEquals(jobDict['input'], self.httpRequest.args['request'][0])
            self.assertEquals(jobDict['output'], None)
        
        # Set self.httpRequest.args dictionary for testing
        self.httpRequest.args = {'request': ['I want to run a marathon']}
        # Set self.httpRequest.channel.factory (to simulate live client connection)
        self.httpRequest.channel.factory = self.serverFactory
        # Create new job instance for testing
        self.httpRequest.job = job.Job(self.httpRequest.channel.factory.workflow, self.httpRequest.channel.factory.name)
        return self.httpRequest.job.init().addCallback(processResponse)

if __name__=="__main__":
    unittest.pyunit.main()
