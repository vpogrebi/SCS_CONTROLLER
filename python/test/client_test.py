'''
Created on Jul 23, 2009

@author: valeriypogrebitskiy
'''
import sys
import client
import test_lib
import twisted_logger

import simplejson as json 
from deferred_lib import sleep
from twisted.trial import unittest
from twisted.python import log, failure
from twisted.protocols.basic import LineReceiver
from twisted.internet import defer, reactor, protocol

# Set client.client_request.scheduleChecks to False - to avoid job STATUS requests being sent to the server
client.client_request.scheduleChecks = False

#config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_localhost.cfg"
config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
params = test_lib.getConfig(config_file)
synchdb = test_lib.getSynchDB(params)

# Start logging
log.startLogging(sys.stdout)

testClientName = 'EES_CLIENT'
testPort = 7000

client.scheduleChecks = True

class ServerProtocol(LineReceiver):
    connDeferred = None
    disconnDeferred = None
    dataRcvdDeferred = None

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
        if data.has_key('type') and data['type'] != 'STATUS':
            self.dataRcvdDeferred.callback(data)
        # Send response back to client
        response = data
        response = {'type': 'RESPONSE', 'status': 0, 'scs_jobid': data['scs_jobid'], 'result_set': data['request'], 'err_msg': None}
        self.sendLine(json.dumps(response))
        
class SCSClientServiceTest(unittest.TestCase):
    logPrefix = None

    def setUp(self):
        self.logPrefix = None
        self.listeningPort = None
        unittest.TestCase.timeout = 10
        self.clientInfo = {'host': 'localhost', 'port': testPort, 'enabled': True}
        self.clientService = client._SCSClientService(testClientName, self.clientInfo, 'TEST_LOG', None)
        return self.clientService.startService()
        
    def tearDown(self):
        deferreds  = []
        try:
            deferreds.append(self.clientService.stopService())            
            if self.listeningPort:
                # Stop server
                deferreds.append(self.listeningPort.stopListening())            
        except:
            pass
        return defer.DeferredList(deferreds)
       
    def test__init__(self):
        "Test that _SCSClientService.__init__() correctly instantiates _SCSClientService entity"
        self.logPrefix = "SCSClientServiceTest.test__init__"
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(self.clientService.name, testClientName)
        self.assertEquals(self.clientService.host, self.clientInfo['host'])
        self.assertEquals(self.clientService.port, self.clientInfo['port'])
        self.assertEquals(self.clientService.peer, "%s:%s" % (self.clientInfo['host'], self.clientInfo['port']))
        self.assertEquals(self.clientService.logName, "TEST_LOG")
        self.assertEquals(self.clientService.clientProtocols, [])
        self.assertEquals(self.clientService.running, 1)        
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")        
    
    def test_startClient(self):
        "Test that _SCSClientService.startClient() successfully starts client"
        self.logPrefix = "SCSClientServiceTest.startClient"
        
        def checkResults(protocol):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(isinstance(protocol, client._SCSClientProtocol), True)
            self.assertEquals(self.clientService.clientProtocols, [protocol])
            self.assertEquals(protocol.connected, 1)        
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")            
            
        # Start test server
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        self.listeningPort = reactor.listenTCP(testPort, factory)

        self.assertEquals(self.clientService.clientProtocols, [])
        return self.clientService.startClient().addCallback(checkResults)
    
    def test_stopService_NO_CLIENTS(self):
        "Test that _SCSClientService.stopService() successfully stops service when there are no client protocols connected to server"
        self.logPrefix = "SCSClientServiceTest.test_stopService_NO_CLIENTS"
            
        def checkResult(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(self.clientService.clientProtocols, [])        
            self.assertEquals(self.clientService.running, 0)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

        self.assertEquals(self.clientService.running, 1)
        self.assertEquals(self.clientService.clientProtocols, [])
        return self.clientService.stopService().addCallback(checkResult)
    
    def test_stopService_MULTIPLE_CLIENTS(self):
        "Test that _SCSClientService.stopService() successfully stops service when there are multiple client protocols connected to server"
        self.logPrefix = "SCSClientServiceTest.test_stopService_MULTIPLE_CLIENTS"
        numClients = 3
        
        def stopService(nothing):
            self.assertEquals(self.clientService.running, 1)            
            self.assertEquals(len(self.clientService.clientProtocols), numClients)        
            twisted_logger.writeLog(self.logPrefix, None, "Client service has started. Stopping service...")            
            return self.clientService.stopService().addCallback(checkResult)
            
        def checkResult(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(self.clientService.clientProtocols, [])        
            self.assertEquals(self.clientService.running, 0)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

        # Start test server
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        self.listeningPort = reactor.listenTCP(testPort, factory)

        deferreds = []
        self.assertEquals(self.clientService.clientProtocols, [])
        
        # Start <numClients> clients
        for num in range(numClients):
            deferreds.append(self.clientService.startClient())
        return defer.DeferredList(deferreds).addCallback(stopService)
    
    def test_sendRequest(self):
        "Test that _SCSClientService.sendRequest() successfully sends request to external server"
        self.logPrefix = "SCSClientServiceTest.test_sendRequest"
        testRequest = {'scs_jobid': 5, 'request': 'I want to run marathon'}
        
        def requestReceivedHandler(data):
            twisted_logger.writeLog(self.logPrefix, None, "Server received request: '%s'" % data)
            
        def checkResults(protocol):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(isinstance(protocol.jobRequest, client.client_request.JobRequest), True)
            self.assertEquals(protocol.jobRequest.request['type'], 'REQUEST')
            self.assertEquals(protocol.jobRequest.scs_jobid, testRequest['scs_jobid'])
            self.assertEquals(protocol.jobRequest.request['request'], testRequest['request'])
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        
        # Start test server
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        factory.protocol.dataRcvdDeferred = defer.Deferred().addCallback(requestReceivedHandler)
        self.listeningPort = reactor.listenTCP(testPort, factory)

        self.assertEquals(self.clientService.clientProtocols, [])
        deferred = defer.Deferred()            
        twisted_logger.writeLog(self.logPrefix, None, "Sending test request to the server...")
        return self.clientService.sendRequest(testRequest, deferred).addCallback(checkResults)
    
    def test_addOnlineDeferred(self):
        "Test that _SCSClientService.addOnlineDeferred() adds deferred to <onlineDeferreds> dictionary, and that entire dictionary is passed on to Monitoring service"
        self.logPrefix = "SCSClientServiceTest.test_addOnlineDeferred"
        self.assertEquals(self.clientService.onlineDeferreds, {})
        for srv in self.clientService:
            if isinstance(srv, client._SCSServerMonitor):
                self.assertEquals(srv.onlineDeferreds, self.clientService.onlineDeferreds)
                break
            
        deferred = defer.Deferred()
        self.clientService.addOnlineDeferred(deferred, reset = True)
        
        self.assertEquals(self.clientService.onlineDeferreds, {deferred: True})
        for srv in self.clientService:
            if isinstance(srv, client._SCSServerMonitor):
                self.assertEquals(srv.onlineDeferreds, self.clientService.onlineDeferreds)
                break
        
    def test_addOfflineDeferred(self):
        "Test that _SCSClientService.addOfflineDeferred() adds deferred to <offlineDeferreds> dictionary, and that entire dictionary is passed on to Monitoring service"
        self.logPrefix = "SCSClientServiceTest.test_addOfflineDeferred"
        self.assertEquals(self.clientService.offlineDeferreds, {})
        for srv in self.clientService:
            if isinstance(srv, client._SCSServerMonitor):
                self.assertEquals(srv.offlineDeferreds, self.clientService.offlineDeferreds)
                break
            
        deferred = defer.Deferred()
        self.clientService.addOfflineDeferred(deferred, reset = True)
        
        self.assertEquals(self.clientService.offlineDeferreds, {deferred: True})
        for srv in self.clientService:
            if isinstance(srv, client._SCSServerMonitor):
                self.assertEquals(srv.offlineDeferreds, self.clientService.offlineDeferreds)
                break
        
class SCSClientManagerTest(unittest.TestCase):
    global db, clientManager
    logPrefix = None
    db = test_lib.getTwistedMySQLdb(params)
    clientManager = client.SCSClientManager(params['log_dir'])

    def setUp(self):
        self.logPrefix = None
        self.listeningPort = None
        unittest.TestCase.timeout = 10
        db.start()
        return clientManager._loadInfo()
        
    def tearDown(self):
        db.close()
        deferreds = []
        deferreds.append(clientManager.stopService())
            
        if self.listeningPort:
            # Stop server
            deferreds.append(self.listeningPort.stopListening())
        return defer.DeferredList(deferreds)
       
    def test__init__(self):
        "Test that SCSClientManager.__init__() correctly loads client info"
        self.logPrefix = "SCSClientManagerTest.test__init__"
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        self.assertEquals(clientManager.namedServices, {})
        
        query = "select c.client_name, c.server_name, s.host, s.port, s.protocol, " \
                "c.enabled from scs.scs_client c, scs.ext_server s where c.server_name = s.server_name"
        res = synchdb.query(query)
        
        self.assertEquals(len(res), len(clientManager.clientInfo.keys()))
        for clientName in clientManager.clientInfo.keys():
            for rec in res:
                if clientName == res[0]:
                    self.assertEquals(clientManager.clientInfo[clientName]['host'], res[1])
                    self.assertEquals(clientManager.clientInfo[clientName]['port'], res[3])
                    self.assertEquals(clientManager.clientInfo[clientName]['enabled'], res[6])
                    break
        twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
    
    def test_start(self):
        "Test that SCSClientManager.start() successfully starts given client service"
        self.logPrefix = "SCSClientManagerTest.test_start"

        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(clientManager.running, 1)
            self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
            clientService = clientManager.namedServices[testClientName]
            self.assertEquals(clientService.running, 1)        
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
        # Start client service
        clientManager.clientInfo[testClientName]['enabled'] = 1
        return clientManager.start(testClientName).addCallback(checkResults)
    
    def test_start_FAILURE_CLIENT_DISABLED(self):
        "Test that SCSClientManager.start() raises exception when starting client defined as disabled"
        self.logPrefix = "SCSClientManagerTest.test_start_FAILURE_CLIENT_DISABLED"

        clientManager.clientInfo[testClientName]['enabled'] = 0
        self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        try:
            clientManager.start(testClientName)
        except RuntimeError, err:
            expect_err = "Client is disabled"
            self.assertEquals(str(err).find(expect_err) > 0, True)
            self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        else:
            err_msg = "CSClientManager.start() does not raise exception when starting client defined as disabled"
            raise self.failureException, err_msg
    
    def test_start_FAILURE_UNKNOWN_CLIENT(self):
        "Test that SCSClientManager.start() raises exception when starting unknown client"
        self.logPrefix = "SCSClientManagerTest.test_start_FAILURE_UNKNOWN_CLIENT"
        unknownClient = 'UNKNOWN_CLIENT'
        self.assertEquals(clientManager.clientInfo.has_key(unknownClient), False)
        twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
        try:
            clientManager.start(unknownClient)
        except RuntimeError, err:
            expect_err = "Unknown client"
            self.assertEquals(str(err).find(expect_err) > 0, True)
            self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
        else:
            err_msg = "CSClientManager.start() does not raise exception when starting unknown client"
            raise self.failureException, err_msg
    
    def test_start_FAILURE_SERVICE_RUNNING(self):
        "Test that SCSClientManager.start() raises exception when starting client service which is already running"
        self.logPrefix = "SCSClientManagerTest.test_start_FAILURE_SERVICE_RUNNING"

        def checkResults(nothing):
            self.assertEquals(clientManager.running, 1)
            self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
            clientService = clientManager.namedServices[testClientName]
            self.assertEquals(clientService.running, 1)        
            twisted_logger.writeLog(self.logPrefix, None, "Starting client service again...")
            try:
                clientManager.start(testClientName)
            except RuntimeError, err:
                twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
                expect_err = "Client service is already running"
                self.assertEquals(str(err).find(expect_err) > 0, True)
                self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
                clientService = clientManager.namedServices[testClientName]
                self.assertEquals(clientService.running, 1)                        
                twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            else:
                err_msg = "CSClientManager.start() does not raise exception when starting client service which is already running"
                raise self.failureException, err_msg
            
        self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
        # Start client service
        clientManager.clientInfo[testClientName]['enabled'] = 1
        return clientManager.start(testClientName).addCallback(checkResults)
    
    def test_start_RESTARTS_STOPPED_CLIENT(self):
        "Test that SCSClientManager.start() restarts client that was previously stopped"
        self.logPrefix = "SCSClientManagerTest.test_start_RESTARTS_STOPPED_CLIENT"
        
        def stopService(nothing):
            self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
            self.assertEquals(clientManager.namedServices[testClientName].running, 1)
            # Verify that clientManager service itself is running
            self.assertEquals(clientManager.running == 1, True) 
            return defer.maybeDeferred(clientManager.stop, testClientName).addCallback(restartService)

        def restartService(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Verifying that '%s' service has stopped..." % testClientName)
            self.assertEquals(clientManager.running, True)
            # Verify that server is deleted from ServerManager.services list and ServerManager.namedServices dictionary
            self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
            twisted_logger.writeLog(self.logPrefix, None, "Service has stopped. Restarting the service...")            
            # Restart the server
            return clientManager.start(testClientName).addCallback(checkResults)

        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
            # Verify that server is listening on a port again
            self.assertEquals(clientManager.namedServices[testClientName].running, 1)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")            
            
        # Start client service
        clientManager.clientInfo[testClientName]['enabled'] = 1
        self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
        return clientManager.start(testClientName).addCallback(stopService)
    
    def test_stop(self):
        "Test that SCSClientManager.stop() successfully stops given server"
        self.logPrefix = "SCSClientManagerTest.test_stop"

        def stopClientService(nothing):
            self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
            self.assertEquals(clientManager.namedServices[testClientName].running, 1)
            deferred = clientManager.stop(testClientName)
            if deferred:
                return deferred.addCallback(checkResults)
            else:
                checkResults(None)    
    
        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            # Verify that server is deleted from Clientmanager.namedServices dictionary
            self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        # Start client service
        clientManager.clientInfo[testClientName]['enabled'] = 1
        self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
        return clientManager.start(testClientName).addCallback(stopClientService)

    def test_startUp_shutDown(self):
        "Test that SCSClientManager.startup() successfully starts all enabled clients, and SCSClientManager.shutDown() stops all running clients"
        self.logPrefix = "SCSClientManagerTest.test_startUp_shutDown"

        def checkAfterStartUp(nothing, origEnabled):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results after startup...")
            for clientname in clientManager.clientInfo.keys():
                self.assertEquals(clientManager.namedServices.has_key(clientname), True)
                self.assertEquals(clientManager.namedServices[clientname].running == 1, True)
                clientManager.clientInfo[clientname]['enabled'] = origEnabled[clientname]
            twisted_logger.writeLog(self.logPrefix, None, "All client services have been started")
            return clientManager.shutDown().addCallback(checkAfterShutDown)
        
        def checkAfterShutDown(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results after shutDown()...")
            for clientname in clientManager.clientInfo.keys():
                self.assertEquals(clientManager.namedServices.has_key(clientname), False)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
                                
        origEnabled = {}    
        for clientName in clientManager.clientInfo:
            origEnabled[clientName] = clientManager.clientInfo[clientName]['enabled']
            clientManager.clientInfo[clientName]['enabled'] = 1

        return clientManager.startUp().addCallback(checkAfterStartUp, origEnabled)
     
    def test_sendRequest(self):
        "Test that SCSClientManager.sendRequest() sends request to remote server and returns deferred that 'fires' when request is sent to the server"
        self.logPrefix = "SCSClientManagerTest.test_sendRequest"
        testRequest = {'scs_jobid': 5, 'request': 'I want to run marathon'}
        
        def sendRequest(nothing):
            self.assertEquals(clientManager.namedServices.has_key(testClientName), True)
            self.assertEquals(clientManager.namedServices[testClientName].running, 1)
            deferred = defer.Deferred()
            twisted_logger.writeLog(self.logPrefix, None, "Executing sendRequest()...")
            return clientManager.sendRequest(testClientName, testRequest, deferred).addCallback(checkResults)

        def checkResults(protocol):            
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(hasattr(protocol, 'jobRequest'), True)
            self.assertEquals(protocol.jobRequest.request['request'], testRequest['request'])
            self.assertEquals(protocol.jobRequest.status, None)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")

        def requestReceivedHandler(data):
            twisted_logger.writeLog(self.logPrefix, None, "Server received request: '%s'" % data)
            
        # Initialize test server
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        factory.protocol.dataRcvdDeferred = defer.Deferred().addCallback(requestReceivedHandler)
        self.listeningPort = reactor.listenTCP(testPort, factory)

        # Reset client's host and port attributes to point to desired test location
        clientManager.clientInfo[testClientName]['port'] = testPort
        # Start client service
        clientManager.clientInfo[testClientName]['enabled'] = 1
        self.assertEquals(clientManager.namedServices.has_key(testClientName), False)
        return clientManager.start(testClientName).addCallback(sendRequest)

if __name__=="__main__":
    unittest.pyunit.main()
