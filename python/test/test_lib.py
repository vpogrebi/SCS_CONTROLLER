'''
Created on Jul 20, 2009

@author: valeriypogrebitskiy
'''
import sys
import mysqldb
import config_parser
from deferred_lib import sleep, sleep_fail
from twisted.python.failure import Failure

def getConfig(configFile = None):    
    "Obtain configuration parameters"
    if configFile is None:
        config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
    return config_parser.getParams(configFile, ('MySQL', 'SCS'))
    
def getSynchDB(params):
    "Initialize and return Synchronous mysqldb.SynchDB instance connected to the database"
    if params.has_key('socket'):
      db = mysqldb.SynchDB(params['server'], params['user'], params['passwd'], socket = params['socket'])
    else: 
        db = mysqldb.SynchDB(params['server'], params['user'], params['passwd'])
    return db

def getTwistedMySQLdb(params):
    "Initialize and return mysqldb.MySQLDB instance - wrapper for Twisted's 'adbapi' module"
    if params.has_key('socket'):
      db = mysqldb.TwistedMySQLdb(params['server'], params['user'], params['passwd'], socket = params['socket'])
    else: 
        db = mysqldb.TwistedMySQLdb(params['server'], params['user'], params['passwd'])
    return db
    
def getAsynchDB(params):
    "Initialize and return Asynchronous mysqldb.AsynchDB instance connected to the database"
    return mysqldb.AsynchDB(params['server'], params['user'], params['passwd'])

def initClientMocks(clientNames, online = False, enabled = True):
    "Initialize list of SCSClientMock entities"
    clients = {}
    for name in clientNames:
        clients[name] = SCSClientMock(name, online, enabled)
        if online:
            clients[name].online = True
    return clients
    
class SCSClientMock(object):
    def __init__(self, clientName, online, enabled = True):
        self.name = clientName
        self.enabled = enabled
        self.online = online
        self.extOnlineDeferreds = {}
        self.extOfflineDeferreds = {}
        
    def addOnlineDeferred(self, deferred, reset = True):
        "Add new external deferred to <self.extOnlineDeferreds> list"
        self.extOnlineDeferreds[deferred] = reset
        
    def addOfflineDeferred(self, deferred, reset = True):
        "Add new external deferred to <self.extOfflineDeferreds> list"
        self.extOfflineDeferreds[deferred] = reset
        
    def clientConnectionLost(self, connector, reason):
        err_msg = "'%s' client has lost connection with the server: %s" % (self.name, reason)
        [deferred.callback(err_msg) for deferred in self.extOfflineDeferreds]
        
    def connectionMade(self):
        self.online = True
        [deferred.callback("Connection made") for deferred in self.extOnlineDeferreds]

    def processRequest(self, request, deferred, type = None):
        if type == "success":
            # Imitate successful completion of job step's execution on remote server
            sleep(None, .3).addCallback(self.__success, request, deferred)
        elif type == "failure":            
            # Imitate failure of job step's execution on remote server
            sleep_fail(None, .3, "TEST FAILURE").addErrback(self.__failure, deferred)
                 
    def __success(self, res, request, deferred):
        if deferred is not None:
            if request is not None:
                deferred.callback(str(request))
            else:
                deferred.callback("success")
            
    def __failure(self, failure, deferred):
        if deferred is not None:
            deferred.errback(failure)
