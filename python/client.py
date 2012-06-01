'''
Created on Jul 22, 2009

@author: valeriypogrebitskiy

client.py is responsible for SCS controller's CLIENT side implementation 

Classes:
    1. SCSClientManager -   Main (public) class. Subclasses from twisted.application.service.MultiService, essentially
                            exposing client (_SCSClientFactory/_SCSClientProtocol) entities as services. This class is 
                            responsible for starting/stopping clients, as well as provides functionality to access 
                            individual client entities (both factory and protocol), to send requests to external servers, 
                            and to add external online/offline deferreds to clients.
                            This class Implements IResourceManager interface                        
    2. _SCSClientService -  Wraps individual client functionality (_SCSClientFactory/_SCSClientProtocol) as service. 
                            This class subclasses from twisted.application.service.MultiService and is responsible for
                            starting/stopping individual clients, as well as for initializing log and error files 
                            associated with each client entity                        
    3. _SCSClientFactory -  Extends twisted.internet.protocol.ReconnectingClientFactory class. This class is responsible
                            for managing connection between client and a server                        
    4. _SCSClientProtocol - Extends twisted.protocols.basic.LineReceiver class. This class is responsible for
                            maintaining client/server protocol, sending requests to external server and receiving 
                            responses from external server
'''
__docformat__ = 'epytext'

import os
import copy 
import singleton
import twisted_logger
import client_request
import simplejson as json

from service import addService
from deferred_lib import deferred
from mysqldb import TwistedMySQLdb
from zope.interface import implements
from twisted.application import service
from resource_manager import IResourceManager
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor, defer, protocol, task

scheduleChecks = True # Dictates whether or not regular server connection checks should be performed   
#scheduleChecks = False # Dictates whether or not regular server connection checks should be performed   

class _SCSClientProtocol(LineReceiver):
    """Implements client's protocol functionality. Extends twisted.protocols.basic.LineReceiver protocol class
    This class is responsible for sending requests to, and processing responses received from external server
    """
    def __init__(self, name, peer):
        self.peer = peer
        self.jobRequest = None
        # Initialize deferred that will be used to signal disconnect event
        self.deferred = defer.Deferred()
        self.name = self.logName = self.logPrefix = name
        
    def __del__(self):
        if hasattr(self, 'jobRequest'):
            del self.jobRequest

    def __checkResponse(self, response):
        """Verify that supplied data is a valid response message
        
        @param response: RESPONSE message (dictionary) received from the server
        """
        validTypes = ['ACCEPT', 'RESPONSE', 'STATUS']
        requiredKeys = ['type', 'scs_jobid']
        
        # <response> data obtained after loading JSON message is supposed to be of a dictionary type
        for key in requiredKeys:
            if not response.has_key(key):
                err_msg = "response data does not specify '%s' data" % key
                raise RuntimeError, err_msg
        
        if response['type'] not in validTypes:
            err_msg = "response message has invalid 'type' ('%s'). Valid values: %s" % (response['type'], validTypes)
            raise RuntimeError, err_msg

        return  response
    
    def _stopJobRequest(self):
        "Stop currently running JobRequest"
        if hasattr(self, 'jobRequest') and self.jobRequest and not self.jobRequest.stopped:
            self.jobRequest._stop()
        
    def sendLine(self, data):
        "Send data to remote server"
        # <data> has to be JSON-encoded before being sent to remote server
        twisted_logger.writeLog(self.logPrefix, self.logName, "Sending data to remote server: %s..." % data)
        LineReceiver.sendLine(self, json.dumps(data))
    
    def lineReceived(self, response):
        """Process response received from the server
        
        @param response: data received from external server
        @type response: dictionary
        
        @attention: <response> message should be in the following form:
                    {'type': <response type>, 'scs_jobid': <jobid>, ...}
        """
        response = json.loads(response)
        twisted_logger.writeLog(self.logPrefix, self.logName, "Received message: %s" % response)
        try:
            # Verify request message 
            response = self.__checkResponse(response)
        except RuntimeError, err:
            err_msg = "Invalid response received from %s: %s" % (self.peer, str(err)) 
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            if hasattr(self, 'jobRequest') and not self.jobRequest.stopped:
                self.jobRequest._stop()
        else:
            jobID = response['scs_jobid']
            responseType = response['type']

            # Verify that there is JobRequest instance associated with the given job
            if not hasattr(self, 'jobRequest'):
                err_msg = "request instance associated with job #%d is not found" % jobID
                twisted_logger.writeErr(self.logPrefix, self.logName, "%s: %s" % (err_prefix, err_msg))
                self.transport.loseConnection()
            else:
                err_prefix = "Failure processing external server's '%s' response corresponding to job #%d" % (response['type'], jobID)
            
                # Delete 'type' key/value from <response>
                del response['type']
                try:                    
                    if responseType == 'RESPONSE':
                        # Process given job response
                        self.jobRequest.processResponse(response)
                    elif responseType == 'STATUS':                        
                        # Process given job status response
                        self.jobRequest.statusRequest.processResponse(response)
                    elif responseType == 'ACCEPT':
                        twisted_logger.writeLog(self.logPrefix, self.logName, "Received 'ACCEPT' response for scs_jobid #%d" % jobID)
                        self.jobRequest.accepted = True
                        if client_request.scheduleChecks:
                            twisted_logger.writeLog(self.logPrefix, self.logName, "Initiating status checks for scs_jobid #%d" % jobID)
                            self.jobRequest.statusRequest._startStatusChecks()
                except RuntimeError, err:
                    twisted_logger.writeErr(self.logPrefix, self.logName, "%s: %s" % (err_prefix, str(err)))
                    if responseType == 'RESPONSE':
                        if not self.jobRequest.stopped:
                            self.jobRequest._stop()

            if self.jobRequest.stopped:
                self.transport.loseConnection()
                 
    def sendRequest(self, request, deferred = None):
        """Send request to external server
        
        @param request: request message (dictionary) to be sent to external server
        @param deferred: deferred to be associated with the given job (for job request only)
        @type request: dictionary containing {'scs_jobid': <jobid>, 
                                              'request': <request - text>}
        @type deferred: defer.Deferred instance 
        """
        # Reset <self.logPrefix> to include 'scs_jobid'
        self.logPrefix += ' JOBID #%d' % request['scs_jobid']
        try:
            # Create JobRequest instance that will be responsible for: 
            # 1. processing job request
            # 2. scheduling regular job 'STATUS' requests
            # 3. Handling job response - when it comes from the server
            self.jobRequest = client_request.JobRequest(request, deferred, self)
            # Process job request
            self.jobRequest.processRequest()
        except RuntimeError, err:
            twisted_logger.writeErr(self.logPrefix, self.logName, str(err))
            if isinstance(deferred.__class__, defer.Deferred):
                twisted_logger.writeLog(self.logPrefix, self.logName, "Executing external job step deferred's errback() to report job start failure")                
                deferred.errback(failure.Failure(str(err)), RuntimeError)
        
    def connectionMade(self):        
        "Client's connection event handler"
        peer = self.transport.getPeer()        
        self.peer = "%s:%d" % (peer.host, peer.port)        
        twisted_logger.writeLog(self.logPrefix, self.logName, "Connected to '%s'" % self.peer)
            
    def connectionLost(self, reason = protocol.connectionDone):
        protocol.Protocol.connectionLost(self, reason)
        twisted_logger.writeLog(self.logPrefix, self.logName, "Disconnected from '%s'" % self.peer)
        self.deferred.callback(self)
    
class _SCSClientService(service.MultiService):
    """Extends twisted.application.service.MultiService class
    
    This class "wraps" SCS client functionality (_SCSClientProtocol) as
    a service. It is responsible for starting/stopping the service (initializing 
    log and error files, as well as starting subordinate server monitoring service) 
    used by client entity. It has method(s) for starting "one-off" client connections
    to external server and sending job request to the server
    """
    def __init__(self, name, clientInfo, logName, logDir):
        """Class's constructor. Parameters:
        
        @param name:         SCS client name
        @param clientInfo:   dictionary containing following key/value pairs:
                             - 'host':        server's hostname
                             - 'port':        port on which server is listening
        @param logName:      unique log/error name (identifier) that will be used to write to these particular files
        @param logDir:       folder where log and error files will be created
        """
        try:
            self._checkInfo(clientInfo)
        except RuntimeError, err:
            err_msg = "Invalid client info supplied: %s" % str(err)
            raise RuntimeError, err_msg
        
        if not clientInfo['enabled']:
            err_msg = "Failure starting '%s' client service: client is disabled" % name
            raise RuntimeError, err_msg
        
        service.MultiService.__init__(self)
        
        self.name = name
        self.host = clientInfo['host']
        self.port = clientInfo['port']
        self.peer = "%s:%d" % (self.host, self.port)
        
        self.logDir = logDir
        self.logName = logName
        self.logPrefix = "%s SERVICE" % self.name
        self.logFileName = self.name

        self.deferreds = []
        self.clientInfo = clientInfo                
        self.clientProtocols = []
        
        self.online = False
        self.onlineDeferreds = {}
        self.offlineDeferreds = {}                    
        
        # Create ClientCreator instance that will be responsible for starting client connections
        self.clientCreator = protocol.ClientCreator(reactor, _SCSClientProtocol, self.name, self.peer)
        
    def _checkInfo(self, info):
        """Verify that supplied client info contains all required data
        
        @param info: dictionary (C{dict}) containing following required data:
                     'host':     hostname where server is running
                     'port':     port on which server is listening
                     'enabled':  True/False flag indicating if given client is enabled or not
        @raise RuntimeError: if <info> is not a dictionary, or any of the required data is missing
        """
        if not isinstance(info, dict):
            err_msg = "<info> is not a dictionary (%s is supplied)" % type(info)
            raise RuntimeError, err_msg
        
        requiredKeys = ['host', 'port', 'enabled']
        for key in requiredKeys:
            if not info.has_key(key):
                err_msg = "'%s' data is missing" % key
                raise RuntimeError, err_msg
        
    def _sendRequest(self, protocol, request, deferred):
        """Send request to external server
        
        @param protocol: _SCSClientProtocol instance which is being used to send request to server
        @param request: Request data (whatever it might be) to be sent to external server
        @param deferred: deferred (C{defer.Deferred}) to be used by client protocol to signal job completion or failure
        @return: protocol - client protocol instance (C{_SCSClientProtocol}) that sent request to the server
        """
        if protocol:
            try:
                protocol.sendRequest(request, deferred)
            except:
                raise 
        return protocol
        
    def _connSuccessHandler(self, protocol):
        "Client connection's success handler"
        msg = "Connected to '%s' server" % self.peer
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        # Add callback and errback methods to be used to signal client's connection event
        protocol.deferred.addCallback(self._disconnSuccessHandler).addErrback(self._disconnFailureHandler)
        if isinstance(protocol, _SCSClientProtocol):
            # Client connection is established. <result> - is SCSClientProtocol instance
            self.clientProtocols.append(protocol)
            # Add given client protocol's deferred to <self.deferreds>
            self.deferreds.append(protocol.deferred)
            
        # Cleanup client deferreds
        for d in self.deferreds:
            if d.called == 1:
                self.deferreds.remove(d)                
                                                       
        return protocol
        
    def _connFailureHandler(self, fail):
        "Client connection's failure handler"
        err_msg = "Connection failure: %s" % fail.getErrorMessage()
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        fail.trap(Exception)

        # Cleanup client deferreds
        for d in self.deferreds:
            if d.called == 1:
                self.deferreds.remove(d)
                                                       
#        return fail
                
    def _disconnSuccessHandler(self, protocol):
        "Client disconnect success handler"
        msg = "Disconnected from '%s' server" % self.peer
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        if protocol in self.clientProtocols:
            self.clientProtocols.remove(protocol)        
        # Delete protocol's deferred nad protocol entity itself
        del protocol.deferred
        del protocol

        for d in self.deferreds:
            if d.called == 1:
                self.deferreds.remove(d)
                                                               
    def _disconnFailureHandler(self, failure, protocol):
        "Client disconnect failure handler"
        err_msg = "Client disconnect failure: %s" % failure.getErrorMessage()
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        fail.trap(Exception)
        # Delete protocol's deferred nad protocol entity itself
        del protocol.deferred
        del protocol

        for d in self.deferreds:
            if d.called == 1:
                self.deferreds.remove(d)

    def startClient(self):
        """Start new client connection
        
        @return: deferred (C{defer.Deferred}) - deferred that will 'fire' when client connection is made (or fails)
        """
        msg = "Starting new client connection to %s..." % self.peer
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        deferred = self.clientCreator.connectTCP(self.host, self.port)
        # Add callback and errback methods to be used to signal client's connection event
        deferred.addCallback(self._connSuccessHandler).addErrback(self._connFailureHandler)
        self.deferreds.append(deferred)
        return deferred
        
    def stopClient(self, protocol):
        """Stop client connection
        
        @param protocol: client protocol entity (C{_SCSClientProtocol}) being disconnected from the server
        @return: deferred (C{defer.Deferred}) - deferred that will 'fire' when client has disconnected from server (or fails)
        """
        if isinstance(protocol, _SCSClientProtocol):
            msg = "Disconnecting client connection from %s..." % self.peer
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
            protocol.transport.loseConnection()
            return protocol.deferred
        
    def startService(self):
        "Start SCSClient service"
        twisted_logger.writeLog(self.logPrefix, self.logName, "Starting '%s' service..." % self.name)
        actions = []
        
        if self.logDir:
            # Initialize and start log and error services
            msg = "Opening '%s.log' and '%s.err' files in '%s' folder..." % (self.logFileName, self.logFileName, self.logDir)
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
            twisted_logger.initLogging(self.name, self.logFileName, self.logDir, self)
            for loggerService in self.services:
                if not loggerService.running:
                    actions.append(defer.maybeDeferred(loggerService.startService))

        if scheduleChecks:
            monitoringService = _SCSServerMonitor(self.name, self.clientInfo, self.logName, self.logDir)
            self.addService(monitoringService)
            monitoringService.parent = self
            monitoringService.onlineDeferreds = self.onlineDeferreds
            monitoringService.offlineDeferreds = self.offlineDeferreds
            actions.append(defer.maybeDeferred(monitoringService.startService))
        
        service.Service.startService(self)
        return defer.DeferredList(actions)
        
    def stopService(self):
        "Stop SCSClient service"
        twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
        actions = []
        
        if self.running:
            for clientProtocol in self.clientProtocols[:]:
                if hasattr(clientProtocol, 'jobRequest'):
                    clientProtocol._stopJobRequest()
                if clientProtocol.connected == 1:
                    msg = "Client is being disconnected from %s server..." %  self.peer
                    twisted_logger.writeLog(self.logPrefix, self.logName, msg)
                    actions.append(self.stopClient(clientProtocol))
                
            for srv in self.services[:]:
                try:
                    deferred = self.removeService(srv)
                    if deferred:
                        actions.append(deferred)
                except Exception, err:
                    twisted_logger.writeErr(self.logPrefix, self.logName, "Failure stopping '%s' service: %s" % (srv.name, str(err)))
                
            service.Service.stopService(self)    

        for d in self.deferreds:
            if d.called == 0:
                actions.append(d)
                
        return defer.DeferredList(actions)
    
    def sendRequest(self, request, deferred):
        """Send request to external server
        
        @param request: Request data (whatever it might be) to be sent to external server
        @param deferred: job step deferred (C{defer.Deferred}) to be used by client protocol to signal job completion or failure
        @return: deferred (C{defer.Deferred}) that will fire callback or errback method when request is sent to the server
        """
        d = self.startClient().addCallback(self._sendRequest, request, deferred)
        self.deferreds.append(d)
        return d
    
    def addOnlineDeferred(self, deferred, reset = True):
        if not deferred in self.onlineDeferreds:
            self.onlineDeferreds[deferred] = reset
            
    def addOfflineDeferred(self, deferred, reset = True):
        if not deferred in self.offlineDeferreds:
            self.offlineDeferreds[deferred] = reset

class _SCSServerMonitor(_SCSClientService):
    def __init__(self, name, clientInfo, logName, logDir):
        """Class's constructor. Parameters:
        
        @param name:         SCS client name
        @param clientInfo:   dictionary containing following key/value pairs:
                             - 'host':        server's hostname
                             - 'port':        port on which server is listening
        @param logName:      unique log/error name (identifier) that will be used to write to these particular files
        @param logDir:       folder where log and error files will be created
        """
        _SCSClientService.__init__(self, name, clientInfo, logName, logDir)
        self.logPrefix = "%s SERVER MONITOR" % self.name
        self.name = "%s_MONITOR" % self.name
        # Set server monitor specific attributes
        self.loop = None
        self.serverCheckInterval = 120
                
    def _startServerChecks(self, now = True):
        "Schedule server connection monitoring to run in a loop with given time interval"
        self.loop = task.LoopingCall(self.startClient)
        self.loop.start(self.serverCheckInterval, now)

    def _connSuccessHandler(self, protocol):
        "Client connection's success handler"
        _SCSClientService._connSuccessHandler(self, protocol)
            
        if not self.online:
            # Set <self.online> flag to True and execute callbacks of all of the online deferreds
            self.online = True            
            self.parent.online = True            
            for deferred in self.onlineDeferreds.keys():
                if deferred.called == 0:
                    callbacks = deferred.callbacks[:]
                    twisted_logger.writeLog(self.logPrefix, self.logName, "Executing online workflow callback...")
                    deferred.callback("ok")
                    if self.onlineDeferreds[deferred]:
                        # Reset deferred's <called> and <callbacks> attributes - so deferred's callbacks can be called again
                        deferred.called = 0
                        deferred.callbacks = callbacks
                    
        return protocol
        
    def _connFailureHandler(self, fail):
        "Client connection's failure handler"
        _SCSClientService._connFailureHandler(self, fail)

        if self.online:
            # Set <self.online> flag to False and execute callbacks of all of the offline deferreds
            self.online = False
            self.parent.online = False
            for deferred in self.offlineDeferreds.keys():
                if deferred.called == 0:
                    callbacks = deferred.callbacks[:]
                    twisted_logger.writeLog(self.logPrefix, self.logName, "Executing offline workflow callback...")
                    deferred.callback("error")
                    if self.offlineDeferreds[deferred]:
                        # Reset deferred's <called> and <callbacks> attributes - so deferred's callbacks can be called again
                        deferred.called = 0
                        deferred.callbacks = callbacks

#        return fail
                
    def startClient(self):
        """Start new client connection
        
        @return: deferred (C{defer.Deferred}) - deferred that will 'fire' when client connection is made (or fails)
        """
        deferred = _SCSClientService.startClient(self)
        deferred.addCallback(self.stopClient)
        return deferred
        
    def startService(self):
        "Start monitoring service"
        twisted_logger.writeLog(self.logPrefix, self.logName, "Starting '%s' service..." % self.name)        
        if scheduleChecks:
            # Start server connection checks (monitoring)
            self._startServerChecks()        
        return service.Service.startService(self)
        
    def stopService(self):
        "Stop SCSClient service"
        twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
        actions = []
        
        if self.running:
            for clientProtocol in self.clientProtocols:
                if clientProtocol.connected == 1:
                    msg = "Client is being disconnected from %s server..." %  self.peer
                    twisted_logger.writeLog(self.logPrefix, self.logName, msg)
                    actions.append(self.stopClient(clientProtocol))
                
            if self.loop and self.loop.running:
                # Cancel scheduled server connection checks
                self.loop.stop()
                
            service.Service.stopService(self)    

        for d in self.deferreds:
            if d.called == 0:
                actions.append(d)
                
        return defer.DeferredList(actions)
    
class SCSClientManager(singleton.Singleton, service.MultiService):
    """SCSClient's main (public) class. Manages individual clients and exposes them to user as services.
    
    Implements general SCS client management functionality. Implemented using Singleton design pattern 
    (extends <singleton.Singleton>) and ensures that class gets initialized only once - no matter how many 
    times constructor is called (uses @singleton.uniq() decorator for its __init() constructor
    
    Implements IResourceManager interface
    
    Extends twisted.application.service.MultiService class. Using MultiService class's functionality - 
    exposes individual clients as services. Responsible for starting/stopping client services, access
    to individual client entities, and provides functionality to send requests to external servers to 
    which individual clients are connected
    """
    
    implements(IResourceManager)

    @singleton.uniq
    def __init__(self, logDir = None):
        """Class's constructor. Parameters:
        
        @param logDir: folder where log and error files maintained by SCSClientManager and individual 
                       client services should be created. Optional. Default: current working directory
        """
        service.MultiService.__init__(self)
        self.clientInfo = {}    # Dictionary that will be loaded with resource information, keyed by resource name

        self.name = 'ClientManager'
        self.logDir = logDir
        self.logName = self.name
        self.logPrefix = 'CLIENT_MANAGER'
        
        try:
            self._loadInfo()
        except:
            raise 
        
    def _loadInfo(self):
        """Load <self.clientInfo> dictionary with client configuration data (from scs.scs_client 
        and scs.ext_server tables) for all SCS clients"""
        self.clientInfo = {}
        query = "select c.client_name, s.host, s.port, c.enabled from scs.scs_client c, " \
                "scs.ext_server s where c.server_name = s.server_name"
        db = TwistedMySQLdb()
        return db.query(query).addCallback(self._loadInfoComplete).addErrback(self._loadInfoFailure, query)

    def _loadInfoFailure(self, fail, query):
        "Client data load failure handler"
        err_msg = "Failure loading workflow info: %s" % fail.getErrorMessage()
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        twisted_logger.writeErr(self.logPrefix, self.logName, "SQL Query: '%s'" % query)
        
    def _loadInfoComplete(self, result):
        "Client info SQL load success handler. Completes load of self.clientInfo dictionary"
        if result == ():
            err_msg = "SCS client data is not setup properly"
            twisted_logger.writeLog(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
        
        for (client_name, host, port, enabled) in result:
            self.clientInfo[client_name] = {'host': host, 'port': port, 'enabled': enabled}
                            
    def _startupComplete(self, nothing):
        "Client startup completion handler"
        service.Service.startService(self)
        
    def _shutDownComplete(self, nothing):
        "Client shutdown completion handler"
        "Terminate ClientManager service"
        service.Service.stopService(self)
    
    def start(self, name):
        """Start SCS client service <name>
        
        @param name: SCS client name
        @return: deferred which will 'fire' when given client (service) has started
        """
        failPrefix = "Failure starting '%s' SCS client service" % name

        if not self.clientInfo.has_key(name):
            err_msg = "%s: Unknown client" % failPrefix
            twisted_logger.writeLog(self.logPrefix, self.logName, err_msg)                
            raise RuntimeError, err_msg
            
        if not self.clientInfo[name]['enabled']:            
            err_msg = "%s: Client is disabled" % failPrefix
            twisted_logger.writeLog(self.logPrefix, self.logName, err_msg)                
            raise RuntimeError, err_msg
            
        if self.namedServices.has_key(name):
            if self.namedServices[name].running:
                err_msg = "%s: Client service is already running" % failPrefix
                twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)                
                raise RuntimeError, err_msg
            else:
                # Client service has stopped: delete that service before restarting it
                self.removeService(self.getServiceNamed(name))
                
        if not self.running:
            self.running = 1
            
        if self.namedServices.has_key(name):
            clientService = self.namedServices[name]
            defered = clientService.startService()
        else:
            clientService = _SCSClientService(name, self.clientInfo[name], self.logName, self.logDir)
            defered = addService(self, clientService)
                            
        return defered
        
    def stop(self, name):
        """Stop SCS client service <name>
        
        @param name: SCS client name
        @return: deferred which will 'fire' when given client service has stopped
        """
        if not self.namedServices.has_key(name):
            err_msg = "Unable to stop '%s' SCS client: client has not been started" % name
            twisted_logger.writeLog(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
        
        clientService = self.getServiceNamed(name)
        return defer.maybeDeferred(self.removeService, clientService)
            
    def startUp(self):
        """Start all enabled SCS client services. Returns deferred that can be used (externally) to 
        signal successful startup (connection to external servers)
        
        @return: deferred which will 'fire' when all SCS client services have started
        """
        deferreds = []
        for name in self.clientInfo:
            if self.clientInfo[name]['enabled']:
                try:
                    deferreds.append(self.start(name))
                except:
                    pass
            
        return defer.DeferredList(deferreds)
            
    def shutDown(self):
        """Stop all SCS client services. Returns deferred that can be used (externally) to 
        signal successful shutdown (disconnect from servers) of all client services
        
        @return: deferred which will 'fire' when all SCS client services have stopped
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
        """Start ClientManager service. Automatically starts services for all 'enabled' clients
        
        @return: deferred which will 'fire' when all enabled SCS client services have started
        """
        actions = []
        # Initialize log and error service
        baseLogFileName = "client_manager"
        msg = "Opening '%s.log' and '%s.err' files in '%s' folder..." % (baseLogFileName, baseLogFileName, self.logDir)
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        twisted_logger.initLogging(self.name, baseLogFileName, self.logDir, self)
        for srv in self.services:
            if not srv.running:
                actions.append(defer.maybeDeferred(srv.startService))
                
        twisted_logger.writeLog(self.logPrefix, self.logName, "Starting '%s' service..." % self.name)
        deferred = self.startUp()
        if deferred:
            deferred.addCallback(self._startupComplete)
            actions.append(deferred)
            
        return defer.DeferredList(actions)
        
    def stopService(self):
        """Stop ClientManager service. Automatically stops all running SCS client services
        
        @return: deferred which will 'fire' when all client services have stopped
        """
        twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
        deferreds = []
        for srv in self.services[:]:
            deferred = self.removeService(srv)
            if deferred:
                deferreds.append(deferred)
        
        service.Service.stopService(self)
        return defer.DeferredList(deferreds)
        
    def sendRequest(self, name, request, deferred = None):
        """Submit request to remote server for processing and return deferred that will 'fire' when response is received
        
        @param name:     SCS client name - name of the client that should be used to send given request
        @param request:  request being sent to external server
        @param deferred: deferred (twisted.internet.defer.Deferred instance) that should be associated 
                         with the given request. Optional. Default: None
        @return: deferred (C{defer.Deferred}) that will fire when new client connection is established and job request is sent to the server
        """
        if not self.namedServices.has_key(name):
            err_msg = "'%s' client service has not been started" % name
            raise RuntimeError, err_msg

        return self.namedServices[name].sendRequest(request, deferred)
