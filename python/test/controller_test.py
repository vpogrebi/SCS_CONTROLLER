'''
Created on Aug 25, 2009

@author: valeriypogrebitskiy
'''
import os
import sys
import test_lib
import SCS_controller
import twisted_logger

from twisted.python import log
from twisted.trial import unittest
from twisted.internet import defer

config_file = os.environ['CONFIG_FILE']
params = test_lib.getConfig(config_file)
db = test_lib.getTwistedMySQLdb(params)

log.startLogging(sys.stdout)

SCS_controller.client.scheduleChecks = False

class SCSControllerTest(unittest.TestCase):
    def _tearDownComplete(self, nothing):
        twisted_logger.writeLog(self.logPrefix, None, "tearDown() completed")
        
    def setUp(self):
        db.start()
        self.logPrefix = None
        unittest.TestCase.timeout = 10
        self.controller = SCS_controller.SCSController(None)
        
    def tearDown(self):
        db.close()
        return self.controller.stopService().addCallback(self._tearDownComplete)

    def test___init__(self):
        self.logPrefix = "test___init__"
        self.assertEquals(self.controller.namedServices.has_key('ServerManager'), True)
        self.assertEquals(self.controller.namedServices.has_key('ClientManager'), True)
        self.assertEquals(self.controller.namedServices.has_key('ClientManager'), True)
        self.assertEquals(self.controller.namedServices['ServerManager'].running, False)
        self.assertEquals(self.controller.namedServices['ClientManager'].running, False)
        self.assertEquals(self.controller.namedServices['ClientManager'].running, False)
        
    def test_startService(self):
        "Test that SCSController.startService() successfully starts all services"
        self.logPrefix = "test_startService"
        
        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(self.controller.namedServices.has_key('ServerManager'), True)
            self.assertEquals(self.controller.namedServices.has_key('ClientManager'), True)
            self.assertEquals(self.controller.namedServices.has_key('WorkflowManager'), True)
            self.assertEquals(self.controller.namedServices['ServerManager'].running, True)
            self.assertEquals(self.controller.namedServices['ClientManager'].running, True)
            self.assertEquals(self.controller.namedServices['WorkflowManager'].running, True)
            
            # Verify that when Workflow entities have any steps (clients) - corresponding ClientService 
            # entities have non-empty onlineDeferreds and offlineDeferreds dictionaries
            for srv in self.controller.namedServices['WorkflowManager']:
                if isinstance(srv, SCS_controller.workflow._WorkflowService):
                    for step in srv.workflow.steps:
                        clientService = step['client']
                        self.assertNotEquals(clientService.onlineDeferreds, {})
                        self.assertNotEquals(clientService.offlineDeferreds, {})
            
                        for srv1 in clientService.services:
                            if isinstance(srv1, SCS_controller.client._SCSServerMonitor):
                                monitorService = srv1
                                self.assertEquals(monitorService.onlineDeferreds, clientService.onlineDeferreds)
                                self.assertEquals(monitorService.offlineDeferreds, clientService.offlineDeferreds)
                                        
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        return self.controller.startService().addCallback(checkResults)
    
    def test_stopService(self):
        "Test that SCSController.stopService() successfully stops all services"
        self.logPrefix = "test_stopService"
        
        def stopController(nothing):
            self.assertEquals(self.controller.namedServices.has_key('ServerManager'), True)
            self.assertEquals(self.controller.namedServices.has_key('ClientManager'), True)
            self.assertEquals(self.controller.namedServices.has_key('ClientManager'), True)
            self.assertEquals(self.controller.namedServices['ServerManager'].running, True)
            self.assertEquals(self.controller.namedServices['ClientManager'].running, True)
            self.assertEquals(self.controller.namedServices['ClientManager'].running, True)
            twisted_logger.writeLog(self.logPrefix, None, "Stopping SCS SCS_controller...")
            return self.controller.stopService().addCallback(checkResults)
        
        def checkResults(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "SCS controller stopped")
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")
            self.assertEquals(self.controller.namedServices.has_key('ServerManager'), False)
            self.assertEquals(self.controller.namedServices.has_key('ClientManager'), False)
            self.assertEquals(self.controller.namedServices.has_key('ClientManager'), False)            
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        return self.controller.startService().addCallback(stopController)

if __name__=="__main__":
    unittest.pyunit.main()
