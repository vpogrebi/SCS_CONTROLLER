'''
Created on Jul 28, 2009

@author: valeriypogrebitskiy

server.py is responsible for SCS controller's SERVER side implementation 

Classes:
    1. SCSServerManager -   Main (public) class. Subclasses from twisted.application.service.MultiService, essentially
                            exposing server (_SCSServerFactory/_SCSServerProtocol) entities as services. This class is 
                            responsible for starting/stopping servers, as well as provides functionality to access 
                            <listeningPort> instances associated with individual server entities
                            
                            This class Implements IResourceManager interface
                            
    2. _SCSServerService -  Wraps individual server functionality (_SCSServerFactory/_SCSServerProtocol) as service. 
                            This class subclasses from twisted.application.service.MultiService and is responsible for
                            starting/stopping individual servers, as well as for initializing log and error files 
                            associated with each server entity
                            
    3. _SCSServerFactory -  Extends twisted.internet.protocol.Factory class. This class is responsible
                            for managing connection between client and a server
                            
    4. _SCSServerProtocol - Extends twisted.protocols.basic.LineReceiver class. This class is responsible for
                            maintaining client/server protocol, receiving requests from and sending responses 
                            to external clients
'''
__docformat__ = 'epytext'

import job
import os.path
import workflow
import singleton
import twisted_logger
import simplejson as json

from service import addService
from mysqldb import TwistedMySQLdb
from zope.interface import implements
from resource_manager import IResourceManager

from twisted.web import http
from twisted.python import log, failure
from twisted.application import service
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor, defer, protocol, task, error
    
jobStatusMap = {'SUCCESS': 0, 'FAILURE': 1, 'RUNNING': None, 'NEW': None}

class _SCSServerHTTPRequest(http.Request):
    """_SCSServerHTTPRequest class - responsible for processing HTTP requests that come from external clients  
    
    Inherits from twisted.web.http.Request.
    This class is responsible for following functionality related to client's job request management:
    
        1. Processing HTTP job request (starting Job instance that's responsible for executing a sequence  
           of job steps that belong to workflow associated with this server)
        2. Responding to job 'STATUS' requests that can be submitted by external client 
        3. Handling job completion event and reporting its result back to external client

    Constructor parameters and failure conditions:
    
    @param channel: the channel we're connected to.
    @param queued:  are we in the request queue, or can we start writing to
                    the transport?
    """
    def __init__(self, channel, queued):
        """_SCSServerHTTPRequest class's constructor
        
        @param channel: the channel we're connected to.
        @param queued: are we in the request queue, or can we start writing to
            the transport?
        """
        http.Request.__init__(self, channel, queued)

        self.job = None
        self.error = None
        self.status = None
        self.response = None

    def __jobStartHandler(self, result):
        "Report job start success or failure to the client that sent this job request"        

        if isinstance(result, failure.Failure):
            # Job start failure
            self.status = jobStatusMap['FAILURE']
            self.error = "Job start failure"
            err_msg = "%s: %s" % (self.error, result.getErrorMessage())
            twisted_logger.writeErr(self.channel.logPrefix, self.channel.logName, err_msg)
            # Trap failure event
            result.trap(Exception)
            # Delete job entity (it is not going to be processed anyway)
            del self.job
            self.job = None

            # Send failure response to external client
            self._sendError(http.INTERNAL_SERVER_ERROR, self.error)
            self.finish()
        else:
            msg = "New job #%d has been created. Status: '%s'" % (self.job.jobID, self.job.status)
            twisted_logger.writeLog(self.channel.logPrefix, self.channel.logName, msg)
            # Add job info to server factory's jobInfos dictionary
            self.channel.factory.jobInfos[self.job.jobID] = {'status': self.job.status, 'error': self.job.error,
                                                             'input': self.job.input, 'output': self.job.output}
            return "ok"
        
    def _runJob(self, nothing):
        """Execute (start) Job associated with the given request
        
        @return: deferred which will 'fire' when Job has started execution 
        """
        # Create deferred that will be called back when job completes (or fails)
        deferred = defer.Deferred().addBoth(self.processResponse)
        return self.job.run(self.args['request'][0], deferred).addBoth(self.__jobStartHandler)
        
    def _sendError(self, code, resp=None):
        "Send error notification to the client"
        self.setResponseCode(code, resp)
#        self.write('%s %s %s\r\n\r\n' % (self.clientproto, code, self.code_message))
        if resp is None:
            resp = ''
        self.write(resp)
                    
    def _checkRequest(self):
        """Verify that supplied request has correct format and required data
        
        This method verifies that supplied request (stored as <self.args>) contains
        actual request data (self.args['request'] dictionary item)
        """
        requiredKeys = ['request']
        
        # <response> data obtained after loading YAML message is supposed to be of a dictionary type
        for key in requiredKeys:
            if not self.args.has_key(key):
                err_msg = "request data does not specify '%s' data (args: '%s')" % (key, self.args)
                raise RuntimeError, err_msg
        
    def _sendResponse(self, response, code = None, code_message = None):
        "Send response to the client"
        if code:
            self.setResponseCode(code, code_message)
            
        msg = "Sending response to %s client: %s" % (self.channel.peer, response)
        twisted_logger.writeLog(self.channel.logPrefix, self.channel.logName, msg)        
        try:
            self.write(str(response))
        except Exception, err:
            err_msg = "Failure sending '%s' response to %s: %s" % (response['type'], self.channel.peer, str(err))
            twisted_logger.writeErr(self.channel.logPrefix, self.channel.logName, err_msg)            
        
    def _checkWorkflowStatus(self):
        "Check if workflow associated with the server is offline or disabled"
        error = None
        
        workflow = self.channel.factory.workflow
        if workflow:
            if not workflow.enabled:
                # Workflow is disabled: reject processing new client's request
                error = "'%s' workflow is disabled" % workflow.name
            elif not workflow.online:
                # Workflow is offline: reject processing new client's request
                error = "'%s' workflow is offline" % workflow.name
            
            if error:    
                raise RuntimeError, error

    def process(self):
        """Process job request - start job (job.Job instance) to execute a set of job steps associated with the server's workflow

        @note: This method simply creates Job instance and starts its execution
        @return: deferred which will 'fire' when Job instance is initialized and 
                 first JobStep has started execution
        """
        try:
            self._checkRequest()
        except RuntimeError, err:
            error = str(err)
            err_msg = "Invalid request received from %s: %s" % (self.channel.peer, error)
            twisted_logger.writeErr(self.channel.logPrefix, self.channel.logName, err_msg)
            # Send failure response to the client
            self._sendError(http.BAD_REQUEST, 'Invalid request: %s' % error)            
            self.finish()
        else:
            try:
                # Check if workflow associated with the server is offline or disabled
                self._checkWorkflowStatus()
            except RuntimeError, err:
                error = str(err)
                twisted_logger.writeErr(self.channel.logPrefix, self.channel.logName, error)
                self._sendError(http.INTERNAL_SERVER_ERROR, error)            
                self.finish()
            else:
                try:
                    # Create new job instance
                    self.job = job.Job(self.channel.factory.workflow, self.channel.factory.name)
                except Exception, err:
                    error = str(err)
                    twisted_logger.writeErr(self.channel.logPrefix, self.channel.logName, "Failure creating job.Job instance: %s" % error)
                    self._sendError(http.INTERNAL_SERVER_ERROR, error)            
                    self.finish()
                else:                    
                    # Initialize and start new job. This will return deferred
                    return self.job.init().addCallback(self._runJob)
    
    def processResponse(self, result, sendResponse = True):
        "Process job completion, timeout or failure event"
        self.status = jobStatusMap[self.job.status]
        self.error = self.job.error
        # Update server factory's jobInfos dictionary with current job info
        self.channel.factory.jobInfos[self.job.jobID] = {'status': self.job.status, 'error': self.job.error,
                                                          'input': self.job.input, 'output': self.job.output}

        if isinstance(result, failure.Failure):
            # Generate job failure message to be written to log
            msg = "Job #%d has failed: %s" % (self.job.jobID, self.error)
            # Write message to event log
            twisted_logger.writeErr(self.channel.logPrefix, self.channel.logName, msg)
            if sendResponse:
                # Send job failure response to the client
                self._sendError(http.INTERNAL_SERVER_ERROR, msg)
        else:
            # Generate job success message to be written to log
            msg = "Job #%d has successfully completed" % self.job.jobID
            # Write message to event log
            twisted_logger.writeLog(self.channel.logPrefix, self.channel.logName, msg)
            if sendResponse:
                # Send job results to the client
                self._sendResponse(result, http.OK)
        
        # Delete original job entity
        del self.job
        self.job = None

        if not sendResponse:
            self.finished = True
            
        self.finish()

class _SCSServerProtocol(http.HTTPChannel):
#class _SCSServerProtocol(protocol.Protocol):
    """Implements server's protocol functionality. Derives from twisted.web.http.HTTPChannel
    class (which in turn derives from twisted.protocols.basic.LineReceiver protocol class)"""
    name = None
    peer = None
    logName = None
    logPrefix = None
    requestFactory = _SCSServerHTTPRequest
    
    def __init__(self):
        "Class's constructor"
        http.HTTPChannel.__init__(self)

    def connectionLost(self, reason):
        "Client connection lost"
        msg = "Connection lost with %s client: %s" % (self.peer, reason.getErrorMessage())
        twisted_logger.writeErr(self.logPrefix, self.logName, msg)
        http.HTTPChannel.connectionLost(self, reason)
        
        # Remove itself from factory's protocols list
        if self in self.factory.protocols:
            self.factory.protocols.remove(self)
            
    def connectionMade(self):
        "Client connection made"
        http.HTTPChannel.connectionMade(self)
        peer = self.transport.getPeer()
        self.peer = "%s:%d" % (peer.host, peer.port)
        msg = "Connection established from %s" % (self.peer)
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        if self.factory.numPorts >= self.factory.maxConnections:
            err_msg = "Client connection (%s) rejected: maximum number of client connections reached" % self.peer
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            self.transport.loseConnection()
        else:
            msg = "Client connection from %s is accepted" % (self.peer)
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
    
            if self not in self.factory.protocols:
                # Add protocol (self) to the factory's <factory.protocols> list
                self.factory.protocols.append(self)
                    
class _SCSServerFactory(http.HTTPFactory):
    """Factory for HTTP server. Derives from twisted.web.http.HTTPFactory class"""
    noisy = False
    protocol = _SCSServerProtocol
    
    def __init__(self, name, info = None, logDir = os.getcwd()):
        http.HTTPFactory.__init__(self, os.path.join(logDir, '%s.requests' % name))
        self.name = name
        self.protocols = []
        self.enabled = False
        self.workflow = None
        self.maxConnections = 0
        self.workflowName = None
        self.logName = self.name
        self.logPrefix = self.name

        self.jobInfos = {}
        
        try:
            self.__initialize(info)
        except:
            raise 
                        
    def __initialize(self, info):
        "Initialize given SCS server instance"
        try:
            (self.workflowName, self.maxConnections, self.enabled) = self._checkInfo(info)
        except RuntimeError, err:
            raise RuntimeError, err
            
        try:
            self._setWorkflow()
        except:
            pass
        
    def _checkInfo(self, info):
        """Verify that supplied <info> is a dictionary 
        
        @param info: dictionary containing following key/value pairs:
                    'workflow': <wf_name>
                    'max_connections': <num_connections>
                    'enabled': <bool (True/False)>
        """
        if not isinstance(info, dict):
            err_msg = "Supplied SCS server info must be a dictionary (%s is passed)" % type(info)  
            raise RuntimeError, err_msg
        else:
            for key in ('workflow', 'max_connections', 'enabled'):
                if not info.has_key(key):
                    err_msg = "Supplied information does not contain required '%s' data" % key  
                    raise RuntimeError, err_msg
        return (info['workflow'], info['max_connections'], info['enabled'])
        
    def _setWorkflow(self):
        "Set workflow to be used by the server"
        try:
            workflowManager = workflow.WorkflowManager()
            self.workflow = workflowManager.getResource(self.workflowName)
        except RuntimeError, err:
#            twisted_logger.writeErr(self.logPrefix, self.logName, str(err))
            raise RuntimeError, err            

    def stopFactory(self):
        "Close all client connections and stop listening on a given port"
        msg = "Server factory is being stopped..."
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        
        for connProtocol in self.protocols:
            msg = "Disconnecting %s client's connection..." % connProtocol.peer
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
            connProtocol.transport.loseConnection()
            
        # Stop HTTP factory itself
        http.HTTPFactory.stopFactory(self)
        protocol.Factory.stopFactory(self)
        
    def buildProtocol(self, addr):
        p = http.HTTPFactory.buildProtocol(self, addr)
        # Set protocol entity's logger and name
        p.name = self.name
        p.logName = self.logName
        p.logPrefix = self.logPrefix
        return p
    
    
class _SCSServerService(service.MultiService):
    """Extends twisted.application.service.MultiService class
    
    This class "wraps" SCS server functionality (_SCSServerFactory/_SCSServerProtocol) as
    a service. It is responsible for starting/stopping the service (the server) and for
    initializing log and error files used by server entity.
    """
    def __init__(self, name, info, logName, logDir):
        """Class's constructor. Parameters:
        
        @param name:     SCS client name
        @param info:     dictionary containing following key/value pairs:
                        'workflow': <wf_name>
                        'max_connections': <num_connections>
                        'enabled': <bool (True/False)>
        @param logName:  unique log/error name (identifier) that will be used to write to these particular files
        @param logDir:   folder where log and error files will be created
        """
        service.MultiService.__init__(self)
        self.name = name
        self.serverInfo = info
        self.listeningPort = None
        
        self.logDir = logDir
        self.logName = logName
        self.logPrefix = "%s SERVICE" % self.name
        self.logFileName = self.name

    def _stopSuccessHandler(self, nothing):
        "Server termination success handler"
        msg = "'%s' server has stopped listening on port #%d" % (self.name, self.serverInfo['port'])
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        
    def _stopFailureHandler(self, failure):
        "Server termination failure handler"
        err_msg = "'%s' server shutdown failure: %s" % (self.name, failure.getErrorMessage())
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)

    def startService(self):
        """Start given SCSServer service
        
        @return: deferred which will 'fire' when all of the service initialization tasks have completed
        """
        actions = []
        failPrefix = "Failure starting '%s' SCS server service" % self.name

        try:
            factory = _SCSServerFactory(self.name, self.serverInfo, self.logDir)
        except RuntimeError, err:
            err_msg = "%s: %s" % (failPrefix, str(err))
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        else:
            msg = "Starting '%s' server on localhost:%d port..." % (self.name, self.serverInfo['port'])
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
    
            try:
                self.listeningPort = reactor.listenTCP(self.serverInfo['port'], factory)
            except Exception, err:
                err_msg = "Failure starting '%s' SCS server service: %s" % (self.name, str(err))
                twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)          
            else:
                # Initialize and start log and error services
                msg = "Opening '%s.log' and '%s.err' files in '%s' folder..." % (self.logFileName, self.logFileName, self.logDir)
                twisted_logger.writeLog(self.logPrefix, self.logName, msg)
                twisted_logger.initLogging(self.name, self.logFileName, self.logDir, self)
                for loggerService in self.services:
                    if not loggerService.running:
                        actions.append(defer.maybeDeferred(loggerService.startService))
                        
        service.Service.startService(self)    
        return defer.DeferredList(actions)
        
    def stopService(self):
        """Stop SCSServer service
        
        @return: deferred which will 'fire' when all of the service termination tasks have completed
        """
        if self.running:
            twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
            actions = []
            
            if not self.listeningPort or not self.listeningPort.connected:
                err_msg = "Unable to stop '%s' server: server not listening on localhost:%d port" % (self.name, self.serverInfo['port'])
                twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            else:
                # Stop running SCS server
                msg = "'%s' server service shutdown in progress..." % self.name
                twisted_logger.writeLog(self.logPrefix, self.logName, msg)
                actions.append(self.listeningPort.stopListening().addCallback(self._stopSuccessHandler).addErrback(self._stopFailureHandler))
            
            for srv in self.services[:]:
                try:
                    deferred = self.removeService(srv)
                    if deferred:
                        actions.append(deferred)
                except Exception, err:
                    twisted_logger.writeErr(self.logPrefix, self.logName, "Failure stopping '%s' service: %s" % (srv.name, str(err)))
                    
            service.Service.stopService(self)    

        return defer.DeferredList(actions)
    
    def getResource(self):
        "Obtain <self.listeningPort> associated with the given server"
        return self.listeningPort
        
class SCSServerManager(singleton.Singleton, service.MultiService):
    """SCSServer's main (public) class. Implements general SCS server management functionality.  
    
    Implemented using Singleton design pattern (extends <singleton.Singleton>) and ensures that 
    class gets initialized only once - no matter how many times constructor is called 
    (uses @singleton.uniq() decorator for its __init() constructor
    
    Implements IResourceManager interface
    
    Extends twisted.application.service.MultiService class. This (MultiService) functionality allows it to
    "wrap" (and expose to user) SCS servers as services that can be started and stopped alltogether when 
    SCSServerManager service itself is being stopped
    """
    
    implements(IResourceManager)
    
    @singleton.uniq
    def __init__(self, logDir = None):
        """Class's constructor. Parameters:
        
        @param logDir: folder where log and error files maintained by SCSServerManager and individual 
                       server services should be created. Optional. Default: current working directory
        """
        service.MultiService.__init__(self)
        self.serverInfo = {}

        self.name = 'ServerManager'
        self.logDir = logDir
        self.logName = self.name
        self.logPrefix = 'SERVER_MANAGER'
                
    def _loadInfo(self):
        "Load <self.resourceInfo> dictionary with server configuration data (from scs.scs_server table) for all SCS servers"
        # Obtain SynchDB instance (connected to the database)
        query = "select server_name, wf_name, port, protocol, max_connections, enabled from scs.scs_server"
        db = TwistedMySQLdb()
        return db.query(query).addCallback(self._loadInfoComplete).addErrback(self._loadInfoFailure, query)
        
    def _loadInfoFailure(self, fail, query):
        "Server data load failure handler"
        err_msg = "Failure loading workflow info: %s" % fail.getErrorMessage()
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        twisted_logger.writeErr(self.logPrefix, self.logName, "SQL Query: '%s'" % query)
        
    def _loadInfoComplete(self, result):
        "Server data load success handler. Completes load of self.serverInfo dictionary"
        if result == ():
            err_msg = "scs.scs_server table contains no server information (empty)"
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
        
        for (server_name, wf_name, port, protocol, max_connections, enabled) in result:
            self.serverInfo[server_name] = {'workflow': wf_name, 'port': port, 'protocol': protocol, 
                                              'max_connections': max_connections, 'enabled': enabled}
                            
    def start(self, name):
        """Start SCS server service <name>
        
        @param name: SCS server name
        @return: deferred which will 'fire' when given server (service) has started
        """
        failPrefix = "Failure starting '%s' SCS server service" % name
        
        if self.namedServices.has_key(name):
            if self.namedServices[name].running:
                err_msg = "%s: Server is already running on port #%d" % (failPrefix, self.serverInfo[name]['port'])
                twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)                
                raise RuntimeError, err_msg
            else:
                # Server service has stopped: delete that service before restarting it
                self.removeService(self.getServiceNamed(name))
                
        if not self.serverInfo[name]['enabled']:
            err_msg = "%s: Server is disabled" % failPrefix
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
            
        if not self.running:
            self.running = 1
            
        if self.namedServices.has_key(name):
            serverService = self.namedServices[name]
            defered = serverService.startService()
        else:
            serverService = _SCSServerService(name, self.serverInfo[name], self.logName, self.logDir)
            defered = addService(self, serverService)
            
        return defered
        
    def stop(self, name):
        """Stop SCS server service <name>
        
        @param name: SCS server name
        @return: deferred which will 'fire' when given service has stopped
        """
        if not self.namedServices.has_key(name):
            err_msg = "Unable to stop '%s' SCS server service: service has not been started" % name
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
        
        serverService = self.getServiceNamed(name)
        return defer.maybeDeferred(self.removeService, serverService)
    
    def startUp(self):
        """Start all enabled SCS server services. Returns deferred that can be used (externally) to 
        signal successful startup of all enabled servers
        
        @return: deferred which will 'fire' when all SCS server services have started
        """
        deferreds = []
        for name in self.serverInfo.keys():
            if self.serverInfo[name]['enabled']:
                try:
                    deferreds.append(self.start(name))
                except:
                    pass
        return defer.DeferredList(deferreds)
    
    def shutDown(self):
        """Stop all SCS server services. Returns deferred that can be used (externally) to 
        signal successful shutdown of all server services
        
        @return: deferred which will 'fire' when all SCS server services have stopped
        """
        deferreds = []
        for serviceName in self.namedServices.keys():
            try:
                deferreds.append(self.stop(serviceName))
            except:
                pass
            
        service.Service.stopService(self)
        return defer.DeferredList(deferreds)
            
    def startService(self):
        """Start ServerManager service. Automatically starts services for all 'enabled' servers
        
        @return: deferred which will 'fire' when all enabled SCS server services have started
        """
        actions = []
        # Initialize and start log and error services
        baseLogFileName = "server_manager"
        msg = "Opening '%s.log' and '%s.err' files in '%s' folder..." % (baseLogFileName, baseLogFileName, self.logDir)
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        twisted_logger.initLogging(self.name, baseLogFileName, self.logDir, self)
        for srv in self.services:
            if not srv.running:
                actions.append(defer.maybeDeferred(srv.startService))
                
        twisted_logger.writeLog(self.logPrefix, self.logName, "Starting '%s' service..." % self.name)
        # Start SCS server services
        actions.append(defer.maybeDeferred(self.startUp))
        service.Service.startService(self)
        return defer.DeferredList(actions)
        
    def stopService(self):
        """Stop ServerManager service. Automatically stops all running SCS server services
        
        @return: deferred which will 'fire' when all client services have stopped
        """
        if self.running:
            twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
            deferreds = []
            for srv in self.services[:]:
                deferred = self.removeService(srv)
                if deferred:
                    deferreds.append(deferred)
                    
            service.Service.stopService(self)
            return defer.DeferredList(deferreds)
            
    def getResource(self, name):
        """Obtain <listeningPort> instance associated with the given SCS server
        
        @param name: SCS server name
        @return: <listeningPort> associated with the given server
        """
        if not self.namedServices.has_key(name):
            err_msg = "'%s' server service has not been started" % name
            raise RuntimeError, err_msg
        return self.namedServices[name].getResource()

    def setWorkflow(self, name):
        "Set server's workflow attribute"
        try:
            listeningPort = self.getResource(name)
            listeningPort.factory._setWorkflow()
        except Exception, err:
            err_msg = "Unable to set server's workflow: %s" % str(err)
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
