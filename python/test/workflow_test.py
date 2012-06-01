'''
Created on Jul 9, 2009

@author: valeriypogrebitskiy
'''
import sys
import client
import test_lib
import workflow
import twisted_logger

from twisted.trial import unittest
from twisted.internet import defer
from deferred_lib import sleep, deferred
from twisted.python.failure import log, Failure

log.startLogging(sys.stdout)

config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
params = test_lib.getConfig(config_file)
# Connect to MySQL database
synchdb = test_lib.getSynchDB(params)
db = test_lib.getTwistedMySQLdb(params)

testWorkflow = 'DORTHY_WORKFLOW'
workflowManager = workflow.WorkflowManager(params['log_dir'])
clientManager = client.SCSClientManager(params['log_dir'])

# Reset workflow.autoDiscovery to False - so Workflow._checkEnabled() does not interfere with test execution
workflow.autoDiscovery = False
# Reset workflow.useDB to False - so Workflow._checkEnabled() and Workflow._checkEnabled() 
# use initial <self.info> instead of executing SQL queries
workflow.useDB = False

global testClientNames
  
class WorkflowManagerTest(unittest.TestCase):
    def _setUpComplete(self, nothing):        
        global testClientNames
        testClientNames = [clientName for clientName in clientManager.clientInfo.keys()]
        self.clients = test_lib.initClientMocks(testClientNames, online = True, enabled = True)
    
    def setUp(self):
        deferreds = []
        self.logPrefix = None
        unittest.TestCase.timeout = 10        
        db.start()
        deferreds.append(clientManager._loadInfo())
        deferreds.append(workflowManager._loadInfo())
        return defer.DeferredList(deferreds).addCallback(self._setUpComplete)
                
    def tearDown(self):
        workflowManager.stopService()
        db.close()
        
    def test__init__(self):
        "Test that WorkflowManager.__init__() correctly loads <scs.workflow_step> info"
        self.logPrefix = "WorkflowManagerTest.test__init__"
        # Check that <workflowManager.namedServices> dictionary is blank
        self.assertEquals(workflowManager.namedServices, {})
        
        query = "select count(distinct wfl.wf_name) from scs.workflow_lookup wfl, scs.workflow_step wfs where wfl.wf_name = wfs.wf_name"
        res = synchdb.query(query)
        numWorkflows = res[0][0]
        
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(numWorkflows, len(workflowManager.workflowInfo.keys()))
        
        for workflowName in workflowManager.workflowInfo.keys():
            self.assertEquals(workflowManager.workflowInfo[workflowName].has_key('enabled'), True)
            self.assertEquals(workflowManager.workflowInfo[workflowName].has_key('timeout'), True)
            self.assertEquals(workflowManager.workflowInfo[workflowName].has_key('steps'), True)            
            for rec in workflowManager.workflowInfo[workflowName]['steps']:
                self.assertEquals(len(rec), 6)  # (step_id, step_no, client_name, input, out_flag, enabled)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
    
    def test_start_FAILURE_DISABLED_WORKFLOW(self):
        "Test that WorkflowManager.start() raises exception when workflow is disabled"
        self.logPrefix = "WorkflowManagerTest.test_start_FAILURE_DISABLED_WORKFLOW"
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = False
        try:
            workflowManager.start(testWorkflow)
        except RuntimeError, err:
            expect_err = "workflow is disabled"
            self.assertEquals(str(err).find(expect_err) >= 0, True)
        else:
            err_msg = "WorkflowManager.start() does not raise exception when starting disabled workflow"
            raise self.failureException, err_msg

    def test_start_FAILURE_UNKNOWN_WORKFLOW(self):
        "Test that WorkflowManager.start() raises exception when workflow is not setup (unknown)"
        self.logPrefix = "WorkflowManagerTest.test_start_FAILURE_UNKNOWN_WORKFLOW"
        dummyWorkflow = 'DUMMY_WF'
        try:
            workflowManager.start(dummyWorkflow)
        except RuntimeError, err:
            expect_err = "unknown workflow"
            self.assertEquals(str(err).find(expect_err) >= 0, True)
        else:
            err_msg = "WorkflowManagerTest.start() does not raise exception when starting unknown (not setup in scs.workflow_lookup table) workflow"
            raise self.failureException, err_msg

    def test_start_SUCCESS(self):
        "Test that WorkflowManager.start() successfully starts workflow service"
        self.logPrefix = "WorkflowManagerTest.test_start_SUCCESS"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), True)
        self.assertNotEquals(workflowManager.namedServices[testWorkflow].workflow, None)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_stop_SUCCESS(self):
        "Test that WorkflowManager.stop() successfully stops workflow service"
        self.logPrefix = "WorkflowManagerTest.test_stop_SUCCESS"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), True)
        self.assertNotEquals(workflowManager.namedServices[testWorkflow].workflow, None)
        workflowManager.stop(testWorkflow)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_disable(self):
        "Test that WorkflowManager.disable() disables workflow"
        self.logPrefix = "WorkflowManagerTest.test_disable"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), True)
        workflow = workflowManager.namedServices[testWorkflow].workflow
        self.assertNotEquals(workflow, None)
        self.assertEquals(workflow.enabled, True)
        # Disable test workflow
        workflowManager.disable(testWorkflow)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflow.enabled, False)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_enable(self):
        "Test that WorkflowManager.enable() enables workflow"
        self.logPrefix = "WorkflowManagerTest.test_enable"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), True)
        workflow = workflowManager.namedServices[testWorkflow].workflow
        self.assertNotEquals(workflow, None)
        self.assertEquals(workflow.enabled, True)
        # Disable test workflow
        workflowManager.disable(testWorkflow)
        self.assertEquals(workflow.enabled, False)
        # Enable test workflow after disabling it
        workflowManager.enable(testWorkflow)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflow.enabled, True)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_getResource(self):
        "Test that WorkflowManager.getResource() returns Workflow entity"
        self.logPrefix = "WorkflowManagerTest.test_getResource"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        workflow = workflowManager.namedServices[testWorkflow].workflow
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflow, workflowManager.getResource(testWorkflow))
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_addOnlineDeferred(self):
        "Test that WorkflowManager.addOnlineDeferred() adds deferred to Workflow entity's extOnlineDeferreds dictionary"
        self.logPrefix = "WorkflowManagerTest.test_addOnlineDeferred"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        workflow = workflowManager.namedServices[testWorkflow].workflow
        self.assertEquals(workflow.extOnlineDeferreds, {})
        # Create test deferred
        deferred = defer.Deferred()
        # Add test deferred to workflow's extOnlineDeferreds dictionary
        reset = False
        workflowManager.addOnlineDeferred(testWorkflow, deferred, reset)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflow.extOnlineDeferreds.has_key(deferred), True)
        self.assertEquals(workflow.extOnlineDeferreds[deferred], reset)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

    def test_addOfflineDeferred(self):
        "Test that WorkflowManager.addOfflineDeferred() adds deferred to Workflow entity's extOfflineDeferreds dictionary"
        self.logPrefix = "WorkflowManagerTest.test_addOfflineDeferred"
        self.assertEquals(workflowManager.namedServices.has_key(testWorkflow), False)
        # Set 'enable' flag to False for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        workflowManager.start(testWorkflow)
        workflow = workflowManager.namedServices[testWorkflow].workflow
        self.assertEquals(workflow.extOfflineDeferreds, {})
        # Create test deferred
        deferred = defer.Deferred()
        # Add test deferred to workflow's extOfflineDeferreds dictionary
        reset = False
        workflowManager.addOfflineDeferred(testWorkflow, deferred, reset)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(workflow.extOfflineDeferreds.has_key(deferred), True)
        self.assertEquals(workflow.extOfflineDeferreds[deferred], reset)
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

class WorkflowTest(unittest.TestCase):
    def _setUpComplete(self, nothing):     
        global testClientNames
        testClientNames = [clientName for clientName in clientManager.clientInfo.keys()]
        self.clients = test_lib.initClientMocks(testClientNames, online = True, enabled = True)
    
    def setUp(self):
        db.start()
        deferreds = []
        self.logPrefix = None
        unittest.TestCase.timeout = 10
        deferreds.append(clientManager._loadInfo())
        deferreds.append(workflowManager._loadInfo())
        return defer.DeferredList(deferreds).addCallback(self._setUpComplete)
        
    def tearDown(self):
        workflowManager.stopService()
        db.close()
        
    def test__init__NO_CLIENTS(self):
        "Test that Workflow.__init__() correctly initializes workflow when no clients have been started"
        self.logPrefix ="WorkflowTest.test__init__NO_CLIENTS"
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Disable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = False
            
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        self.assertEquals(wf.name, testWorkflow)
        self.assertEquals(wf.steps, [])
        self.assertEquals(wf.online, False)
        self.assertEquals(wf.enabled, True)
        self.assertEquals(wf.extOnlineDeferreds, {})
        self.assertEquals(wf.extOfflineDeferreds, {})
        self.assertEquals(isinstance(wf.clientManager, client.SCSClientManager), True)
       
    def test__init__ALL_CLIENTS_ONLINE(self):
        "Test that Workflow.__init__() correctly initializes workflow when all clients have been started and are connected to servers"
        self.logPrefix ="WorkflowTest.test__init__ALL_CLIENTS_ONLINE"
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
            
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        # Artificially set workflow's client data
        wf = workflowManager.getResource(testWorkflow)
        wf._setClients(self.clients.values())
        
        self.assertEquals(wf.name, testWorkflow)
        # Verify that workflow has <workflow.steps> initialized correctly, with 'client' data set - except for the <missingClient>        
        self.assertEquals(len(wf.steps), len(self.clients))
        for i in range(len(wf.steps)):
            stepRec = wf.steps[i]
            infoRec = workflowManager.workflowInfo[testWorkflow]['steps'][i]
            
            self.assertEquals(stepRec['stepID'], infoRec['stepID'])
            self.assertEquals(stepRec['stepNo'], infoRec['stepNo'])
            self.assertEquals(stepRec['clientName'], infoRec['clientName'])
            self.assertEquals(stepRec['inputSrc'], infoRec['inputSrc'])
            self.assertEquals(stepRec['outFlag'], infoRec['outFlag'])
            self.assertEquals(stepRec['enabled'], infoRec['enabled'])
            self.assertEquals(stepRec['client'], self.clients[infoRec['clientName']])
                
        # Check that 'online' status is True - since we have all clients 'online'
        self.assertEquals(wf.online, True) 
        self.assertEquals(wf.enabled, workflowManager.workflowInfo[testWorkflow]['enabled'])
    
    def test__init__NOT_ALL_CLIENTS_STARTED(self):
        "Test that Workflow.__init__() correctly initializes workflow when some, but not all clients have been started"
        self.logPrefix ="WorkflowTest.test__init__NOT_ALL_CLIENTS_STARTED"
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
            
        # Remove one 'client' from clients list - to imitate that one client has not been started
        missingClient = testClientNames[0]
        del self.clients[missingClient]        
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        
        self.assertEquals(wf.name, testWorkflow)
        # Verify that workflow has <workflow.steps> initialized correctly, with 'client' data set - except for the <missingClient>        
        self.assertEquals(len(wf.steps) - 1, len(self.clients))
        for i in range(len(wf.steps)):
            stepRec = wf.steps[i]
            infoRec = workflowManager.workflowInfo[testWorkflow]['steps'][i]
            
            self.assertEquals(stepRec['stepID'], infoRec['stepID'])
            self.assertEquals(stepRec['stepNo'], infoRec['stepNo'])
            self.assertEquals(stepRec['clientName'], infoRec['clientName'])
            self.assertEquals(stepRec['inputSrc'], infoRec['inputSrc'])
            self.assertEquals(stepRec['outFlag'], infoRec['outFlag'])
            self.assertEquals(stepRec['enabled'], infoRec['enabled'])
        
            if infoRec['clientName'] == missingClient:
                self.assertEquals(stepRec['client'], None)
            else:
                self.assertEquals(stepRec['client'], self.clients[infoRec['clientName']])
                
        # Check that 'online' status is False - since we are 'missing' one client
        self.assertEquals(wf.online, False) 
        self.assertEquals(wf.enabled, workflowManager.workflowInfo[testWorkflow]['enabled'])
        
    def test__init__NOT_ALL_CLIENTS_ONLINE(self):
        "Test that Workflow.__init__() correctly initializes workflow when all clients have been started, but some are not connected to servers"
        self.logPrefix ="WorkflowTest.test__init__NOT_ALL_CLIENTS_ONLINE"
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
        # Artificially set 'online' status of one client to False
        self.clients[testClientNames[-1]].online = False
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        # Artificially set workflow's client data
        wf = workflowManager.getResource(testWorkflow)
        wf._setClients(self.clients.values())
        
        self.assertEquals(wf.name, testWorkflow)
        # Verify that workflow has <workflow.steps> initialized correctly, with 'client' data set - except for the <missingClient>        
        self.assertEquals(len(wf.steps), len(self.clients))
        for i in range(len(wf.steps)):
            stepRec = wf.steps[i]
            infoRec = workflowManager.workflowInfo[testWorkflow]['steps'][i]
            
            self.assertEquals(stepRec['stepID'], infoRec['stepID'])
            self.assertEquals(stepRec['stepNo'], infoRec['stepNo'])
            self.assertEquals(stepRec['clientName'], infoRec['clientName'])
            self.assertEquals(stepRec['inputSrc'], infoRec['inputSrc'])
            self.assertEquals(stepRec['outFlag'], infoRec['outFlag'])
            self.assertEquals(stepRec['enabled'], infoRec['enabled'])
            self.assertEquals(stepRec['client'], self.clients[infoRec['clientName']])
                
        # Check that 'online' status is False - since we are 'missing' one client
        self.assertEquals(wf.online, False) 
        self.assertEquals(wf.enabled, workflowManager.workflowInfo[testWorkflow]['enabled'])

    def test_handleClientDisconnect_ONLINE(self):
        "Test that Workflow.handleClientDisconnect() correctly handles client's disconnect when workflow is online"
        self.logPrefix ="WorkflowTest.test_handleClientDisconnect_ONLINE"
        global disconnectHandled, disconnectCount
        
        def handleWorkflowDisconnect(result):
            global disconnectHandled, disconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Workflow.handleClientDisconnect() has been called back ...")
            disconnectCount += 1
            disconnectHandled = True
            
        def checkResults(result, wf):
            "Verify that workflow is OFFLINE and that workflow disconnect is handled (only once)"
            global disconnectHandled, disconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Checking results...")
            self.assertEquals(wf.online, False)
            self.assertEquals(disconnectHandled, True)
            self.assertEquals(disconnectCount, 1)
            twisted_logger.writeLog(self.logPrefix, None, "Success...")
            
        disconnectCount = 0
        disconnectHandled = False

        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True

        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        self.assertEquals(wf.online, True)
        # Add deferred (to Workflow entity) to handle workflow disconnect
        wf.addOfflineDeferred(defer.Deferred().addCallback(handleWorkflowDisconnect), reset = False)
        
        # Imitate clientConnectionLost() event of one of the clients
        self.clients[testClientNames[0]].clientConnectionLost(None, "Test disconnect")
        # Sleep for a fraction of a second before verifying results
        return sleep(None, .1).addCallback(checkResults, wf)

    def test_handleClientDisconnect_OFFLINE(self):
        "Test that Workflow.handleClientDisconnect() correctly handles client's disconnect when workflow is offline"
        self.logPrefix ="WorkflowTest.test_handleClientDisconnect_OFFLINE"
        global disconnectHandled, disconnectCount

        def handleWorkflowDisconnect(result, wf):
            err_msg = "Workflow.handleClientReconnect() resets workflow status to OFFLINE when one client is already OFFLINE"
            raise self.failureException, err_msg

        def checkResults(result, wf):
            "Verify that workflow is OFFLINE and that workflow disconnect event has NOT occured"
            global disconnectHandled, disconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Checking results...")
            self.assertEquals(wf.online, False)
            self.assertEquals(disconnectHandled, False)
            self.assertEquals(disconnectCount, 0)
            twisted_logger.writeLog(self.logPrefix, None, "Success...")
            
        disconnectCount = 0
        disconnectHandled = False

        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True

        # Artificially set one client's online status to False
        self.clients.values()[-1].online = False
        
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())        
        self.assertEquals(wf.online, False)
        # Add deferred (to Workflow entity) to handle workflow disconnect
        wf.addOfflineDeferred(defer.Deferred().addCallback(handleWorkflowDisconnect, wf))

        # Imitate clientConnectionLost() event of one of the clients
        self.clients[testClientNames[0]].clientConnectionLost(None, "Test disconnect")                    
        # Sleep for a fraction of a second before verifying results
        return sleep(None, .1).addCallback(checkResults, wf)            
    
    def test_handleClientReconnect_GO_ONLINE_ONE_DISCONNECTED(self):
        "Test that Workflow.handleClientReconnect() correctly brings Workflow ONLINE when only one client was disconnected"
        self.logPrefix ="WorkflowTest.test_handleClientReconnect_GO_ONLINE_ONE_DISCONNECTED"
        global reconnectHandled, reconnectCount

        def handleWorkflowReconnect(result, wf):
            "Handle workflow reconnect event"
            global reconnectHandled, reconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Workflow.handleClientReconnect() has been called back ...")
            reconnectCount += 1
            reconnectHandled = True
            
        def checkResults(result, wf):
            "Verify that workflow is ONLINE and that workflow reconnect is handled (only once)"
            global reconnectHandled, reconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Checking results...")
            self.assertEquals(wf.online, True)
            self.assertEquals(reconnectHandled, True)
            self.assertEquals(reconnectCount, 1)
            twisted_logger.writeLog(self.logPrefix, None, "Success...")
            
        reconnectCount = 0
        reconnectHandled = False

        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
        
        # Artificially set one client's online status to False
        disconnected_client = testClientNames[-1]
        self.clients[disconnected_client].online = False
        
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        # Verify that workflow's online status is False
        self.assertEquals(wf.online, False)
        
        # Add deferred (to Workflow entity) to handle workflow reconnect
        wf.addOnlineDeferred(defer.Deferred().addCallback(handleWorkflowReconnect, wf))
        # Imitate connectionMade() event of the client that was offline before
        self.clients[disconnected_client].connectionMade()
        # Sleep for a fraction of a second before verifying results
        return sleep(None, .1).addCallback(checkResults, wf)            
        
    def test_handleClientReconnect_GO_ONLINE_MANY_DISCONNECTED(self):
        "Test that Workflow.handleClientReconnect() correctly brings Workflow ONLINE when all OFFLINE clients turn ONLINE"
        self.logPrefix ="WorkflowTest.test_handleClientReconnect_GO_ONLINE_MANY_DISCONNECTED"
        global reconnectHandled, reconnectCount

        def handleWorkflowReconnect(result, wf):
            "Handle workflow reconnect event"
            twisted_logger.writeLog(self.logPrefix, None, "Workflow.handleClientReconnect() has been called back ...")
            global reconnectHandled, reconnectCount
            reconnectCount += 1
            reconnectHandled = True
            
        def checkResults(result, wf):
            "Verify that workflow is ONLINE and that workflow reconnect is handled (only once)"
            global reconnectHandled, reconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Checking results...")
            self.assertEquals(wf.online, True)
            self.assertEquals(reconnectHandled, True)
            self.assertEquals(reconnectCount, 1)
            twisted_logger.writeLog(self.logPrefix, None, "Success...")
                        
        reconnectCount = 0
        reconnectHandled = False

        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
                
        # Artificially set online status to False = for all client instances
        for client in self.clients.values():
            client.online = False 
                    
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        # Verify that workflow's online status is False
        self.assertEquals(wf.online, False)

        # Add deferred (to Workflow entity) to handle workflow disconnect
        wf.addOnlineDeferred(defer.Deferred().addCallback(handleWorkflowReconnect, wf))

        # Imitate connectionMade() event for ALL client that are offline
        for client_name in testClientNames:
            self.clients[client_name].connectionMade()

        # Sleep for a fraction of a second before verifying results
        return sleep(None, .1).addCallback(checkResults, wf)            
        
    def test_handleClientReconnect_DONOTGO_ONLINE(self):
        "Test that Workflow.handleClientReconnect() does not bring Workflow ONLINE when more than one client were disconnected"
        self.logPrefix ="WorkflowTest.test_handleClientReconnect_DONOTGO_ONLINE"
        global reconnectHandled, reconnectCount

        def handleWorkflowReconnect(result, wf):
            global reconnectHandled, reconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Workflow.handleClientReconnect() has been called back ...")
            reconnectCount += 1
            reconnectHandled = True
            err_msg = "Workflow.handleClientReconnect() resets workflow status to online when other client(s) are still offline"
            raise self.failureException, err_msg

        def checkResults(result, wf):
            "Verify that workflow is offline and that workflow reconnect event has not occured"
            global reconnectHandled, reconnectCount
            twisted_logger.writeLog(self.logPrefix, None, "Checking results...")
            self.assertEquals(wf.online, False)
            self.assertEquals(reconnectHandled, False)
            self.assertEquals(reconnectCount, 0)
            twisted_logger.writeLog(self.logPrefix, None, "Success...")
            
        reconnectCount = 0
        reconnectHandled = False
        
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
        
        # Artificially set online status to False = for all client instances
        for client in self.clients.values():
            client.online = False 
                    
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        # Verify that workflow's online status is False
        self.assertEquals(wf.online, False)

        # Add deferred (to Workflow entity) to handle workflow disconnect
        wf.addOnlineDeferred(defer.Deferred().addCallback(handleWorkflowReconnect, wf))

        # Imitate connectionMade() event of ONLY ONE DISCONNECTED client
        self.clients[testClientNames[0]].connectionMade()
        # Sleep for a fraction of a second before verifying results
        return sleep(None, .1).addCallback(checkResults, wf)            

    def test_disable(self):
        "Test that Workflow.disable() sets workflow instance's <enabled> attribute to False"
        self.logPrefix ="WorkflowTest.test_disable"
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
        
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        # Verify that workflow is 'online' and 'enabled'
        self.assertEquals(wf.online, True)
        self.assertEquals(wf.enabled, True)
        
        # Artificially disable workflow
        wf.disable()

        # Verify that workflow is 'online' and 'disabled'
        self.assertEquals(wf.online, True)
        self.assertEquals(wf.enabled, False)
        
    def test_enable(self):
        "Test that Workflow.enable() sets workflow instance's <enabled> attribute to True"
        self.logPrefix ="WorkflowTest.test_enable"
        # Set 'enable' flag to True for the testWorkflow
        workflowManager.workflowInfo[testWorkflow]['enabled'] = True
        # Artificially enable all workflow steps
        for stepRec in workflowManager.workflowInfo[testWorkflow]['steps']:
            stepRec['enabled'] = True
        
        # Start workflow. This should initiate Workflow instance without any 'client' step data
        workflowManager.start(testWorkflow)
        wf = workflowManager.getResource(testWorkflow)
        # Artificially set workflow's client data
        wf._setClients(self.clients.values())
        # Verify that workflow is 'online' and 'enabled'
        self.assertEquals(wf.online, True)
        self.assertEquals(wf.enabled, True)
        
        # Artificially disable workflow
        wf.disable()

        # Verify that workflow is 'online' and 'disabled'
        self.assertEquals(wf.online, True)
        self.assertEquals(wf.enabled, False)

        # Artificially enable workflow
        wf.enable()

        # Verify that workflow is 'online' and 'enabled'
        self.assertEquals(wf.online, True)
        self.assertEquals(wf.enabled, True)

if __name__=="__main__":
    unittest.pyunit.main()
