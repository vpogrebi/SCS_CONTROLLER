'''
Created on Aug 25, 2009

@author: valeriypogrebitskiy

controller.py is main SCS controller system's module. It implements main() function
responsible for initializing and starting the system, and SCSController class that  
exposes main system's components as services and is responsible for starting and
stopping those services (components) in a certain order

Commands to start SCS controller system:

    a. "twistd -y <path/>controller.py" - to start system as a daemon (background) process using 'twistd' utility
    b. "twistd -noy <path/>controller.py" - to start system as a forground process using 'twistd' utility
    c. "python <path/>controller.py" - to start system as an 'independent' forground process

(a) is preferred way of starting SCS controller in production environment
(b) or (c) can be used for debugging or testing
'''
__docformat__ = 'epytext'

import os
import sys

import server
import client
import mysqldb
import workflow
import config_parser

from twisted.python import log
from twisted.internet import reactor, defer
from twisted.python.logfile import DailyLogFile
from twisted.application import service
    
class SCSController(service.MultiService):
    """Main "entry" to SCS controller system. Responsible for initializing, starting and 
    stopping all of the SCS controller system's components.
    
    Main system's components: 
    
    SCSServerManager
    SCSClientManager
    WorkflowManager
    
    Extends twisted.application.service.MultiService class. Using this class's functionality,
    exposes main system's components as services that are being started and stopped alltogether
    """ 
    def __init__(self, logDir):
        """Class's constructor. Initialises ServerManager, ClientManager and 
        WorkflowManager services and sets them as 'children', subordinate to 
        this (self) SCSController instance 
        
        @param logDir: folder where system log and error files will be created
        
        """
        service.MultiService.__init__(self)
        
        serviceInfo = [{'name': 'ServerManager', 'class': server.SCSServerManager},
                       {'name': 'ClientManager', 'class': client.SCSClientManager},
                       {'name': 'WorkflowManager', 'class': workflow.WorkflowManager}]
        
        # Initialize and start SCS controller's services
        for info in serviceInfo:
            try:
                # Create instance of service's class 
                srv = info['class'](logDir)
                self.addService(srv)
            except Exception, err:
                err_msg = "Unable to initialize '%s' service: %s" % (info['name'], err)
                raise RuntimeError, err_msg

    def _setServerWorkflows(self, nothing):
        "Sets workflow associated with each SCS server - after SCS servers and clients have been started"
        serverManager = self.namedServices['ServerManager']
        for serverName in serverManager.serverInfo.keys():
            try:
                serverManager.setWorkflow(serverName)
            except:
                pass
        
    def _startService(self, nothing, serviceName):
        """Deferred's callback handler designated to starting particular service - 
        after some other service (or any method that returns deferred) have completed
        
        @param nothing: value returned ('fired') by deferred - inessential for this method
        @param serviceName: name of the service that is being started
        
        @note: self.namedServices dictionary must have record corresponding to given serviceName
        @raise RuntimeError: if self.namedServices dictionary  does not have <serviceName> key
        @return: deferred which will be fired (callback or errback) when service has started         
        """
        if not self.namedServices.has_key(serviceName):
            err_msg = "'%s' service has not been initialized" % serviceName
            raise RuntimeError, err_msg
        
        return self.namedServices[serviceName].startService()

    def _failureHandler(self, fail):
        """Service startup failure handler
        
        @param fail: twisted.python.failure.Failure instance representing error
        """
        
        err_msg = "Failure starting SCS Controller service: %s" % fail.getErrorMessage()
        fail.trap(Exception)
        raise RuntimeError, err_msg
    
    def startService(self):
        """Start main SCS controller services. 
        Extends twisted.application.service.Service.startService()        
        """
        deferreds = []
        for srv in self.services:
            deferreds.append(srv._loadInfo())
            
        deferred = defer.DeferredList(deferreds)
        deferred.addCallback(self._startService, 'ServerManager').addCallback(self._startService, 'ClientManager')
        deferred.addCallback(self._startService, 'WorkflowManager').addCallback(self._setServerWorkflows)
        deferred.addErrback(self._failureHandler)
        service.Service.startService(self)
        return deferred
            
    def stopService(self):
        "Stop all main SCS controller services"
        global db
        
        deferreds = []
        for serviceName in ('ClientManager', 'ServerManager', 'WorkflowManager'):
            if self.namedServices.has_key(serviceName):
                deferred = self.removeService(self.namedServices[serviceName])
                if deferred:
                    deferreds.append(deferred)
        
        db.close()
        service.Service.stopService(self)
        return defer.DeferredList(deferreds)
        
def main(appName):
    """SCS controller system's MAIN()
    
        1. Loads system's configuration parameters (from file specified by $CONFIG_FILE env. variable
        2. Initialises database connection (instance of mysqldb.TwistedMySQLdb class)
        3. Initialises application root (instance of twisted.application.Application class)
        4. Instantiates controller (SCSController class) and sets <application> instance to be 
           "root" (parent) of that <controller> instance
        5. If started as "independent" Python process: 
           5.1. Start controller's service (controller.startService())
           5.2. Start twisted's reactor (reactor.run())
                  
    Commands:
        a. "twistd -y <path/>controller.py" - to start system as a daemon (background) process using 'twistd' utility
        b. "twistd -noy <path/>controller.py" - to start system as a forground process using 'twistd' utility
        c. "python <path/>controller.py" - to start system as an 'independent' forground process
    
    (a) is preferred way of starting SCS controller in production environment
    (b) or (c) can be used for debugging or testing

    @note: This application can be started in two ways: as a daemon (using 'twistd' utility - option (a)) or
           as "independent" Python process (options (b) or (c))
           
    @return: controller (C{SCSController}) - SCSController instance responsible for system initialization 
                                             and start/stop of main services
    """
    global db, application
    
    try:
        params = config_parser.getConfigParams('MySQL', 'SCS')
    except RuntimeError, err:
        print str(err)
        sys.exit(1)
        
    # Initialize mysqldb.SynchDB class and connect to MySQL database
    if params.has_key('socket'):
        db = mysqldb.TwistedMySQLdb(params['server'], params['user'], params['passwd'], socket = params['socket'])
    else: 
        db = mysqldb.TwistedMySQLdb(params['server'], params['user'], params['passwd'])
    
    # Initialize root level Application entity
    application = service.Application(appName)
    application.params = params

    # Set application's log folder
    if not params.has_key('log_dir') or not os.path.isdir(params['log_dir']):
        if not params.has_key['log_dir']:
            log.msg("'log_dir' configuration parameter is not defined") 
        else:
            log.msg("'%s' folder does not exist or is not accessible" % params['log_dir'])        
        params['log_dir'] = os.getcwd()
    
    log.msg("Using '%s' directory for logging" % params['log_dir'])
    
    try:
        controller = SCSController(params['log_dir'])
    except Exception, err:
        log.err(err)
        sys.exit(1)
        
    controller.setServiceParent(application)    
    return controller

global application
controller = main("SCSController")

if __name__ == '__main__':
    # If started as "independent" Python process - start controller's service and twisted's reactor
    controller.startService()
    reactor.run()
