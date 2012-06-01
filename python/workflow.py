'''
Created on Jul 9, 2009

@author: valeriypogrebitskiy

workflow.py is responsible for SCS controller's WORKFLOW implementation 

Classes:
    1. WorkflowManager -    Main (public) class. Subclasses from twisted.application.service.MultiService, essentially
                            exposing workflow (_Workflow class) entities as services. This class is 
                            responsible for: 
                                - starting/stopping _Workflow services
                                - enabling/disabling _Workflow entities
                                - accessing individual _Workflow entities
                                - adding online/offline deferreds to individual _Workflow entities
                            
                            This class Implements IResourceManager interface
                            
    2. _WorkflowService -   Wraps individual workflow functionality (_Workflow) as service. 
                            This class subclasses from twisted.application.service.MultiService and is responsible for
                            starting/stopping individual workflows, as well as for initializing log and error files 
                            associated with each _Workflow entity
                            
    3. _Workflow -          Implements workflow functionality. This class is responsible for:
                                - setting SCSClient instances associated with the given workflow. This is the main purpose
                                  of having this class. Client entities associated with the workflow define sequence and 
                                  relationship of job steps (JobStep instances) needed to perform each job (Job instance)
                                - enabling/disabling workflow. This feature can (potentially) be used during production 
                                  support issues to temporarily take any workflow "offline"
                                - adding online/offline deferreds that can be used to react to changes in workflow 'online' status
                                - reacting to SCS client entity's loss and restoration of connection with external server                        
'''
__docformat__ = 'epytext'

import os
import copy
import client
import singleton
import twisted_logger

from service import addService
from mysqldb import TwistedMySQLdb

from zope.interface import implements
from twisted.application import service
from twisted.internet import defer, task
from resource_manager import IResourceManager

useDB = True
autoDiscovery = True
checkInterval = 60   # Perform check for enabled/disabled workflow status at this time interval (seconds)

class _Workflow(object):
    """WorkFlow class - implements general SCS workflow functionality"""
    def __init__(self, name, info, logName):
        """WorkFlow class's constructor. 
        
            1. Initializes essential instance attributes;
            2. Sets SCS clients associated with the given workflow;
            3. Verifies if all SCS clients are 'online' and sets workflow.online attribute
            4. Verifies if workflow is enabled and sets workflow.enabled attribute
            5. Schedules regular check of workflow's 'enabled' status

        @param name:    workflow name
        @param info:    <name> - workflow name
                        <info> - dictionary containing workflow step info
                        <logDir> - log directory
        @param logName: unique log/error name (identifier) that will be used to write to these particular files
        
        """
        self.name = name
        self.steps = []
        self.info = info
        self.loop = None
        self.timeout = None
        self.online = False
        self.enabled = False
        self.db = TwistedMySQLdb()        
        self.clientManager = client.SCSClientManager()
        
        self.logName = logName
        self.logPrefix = self.name

        self.extOnlineDeferreds = {}
        self.extOfflineDeferreds = {}

        try:
            clients = self.__initialize()
        except:
            raise
        
        if clients != []:
            self._setClients(clients)
        
        # Execute self._checkEnabled() to see if workflow is enabled (set self.enabled attribute)
        self._checkEnabled()
        # Schedule checking for anabled/disabled status (if <autoDiscovery is True)
        self._scheduleCheckEnabled()
        
    def __initialize(self):
        """Initialize given SCS client instance
        
        @return: clients - a list of started SCSClient instances that belong to given workflow
        """
        if not self.info.has_key('enabled'):
            err_msg = "Workflow information does not have 'enabled' data"
            raise RuntimeError, err_msg
                
        clients = []
        self.enabled = self.info['enabled']
        self.timeout = self.info['timeout']
        
        for infoRec in self.info['steps']:
            if infoRec['enabled']:
                stepRec = {}
                # IMPORTANT: 'client' data will be set by seld.__setClients() - after verifying that
                #            client hass actually been started, and adding workflow's online/offline  
                #            deferreds to client factory's extOnlineDeferreds/extOfflineDeferreds dictionaries
                stepRec = copy.copy(infoRec)
                stepRec['client'] = None
    
                # Try to get client's service instance - if such service has already been started
                if self.clientManager.namedServices.has_key(stepRec['clientName']):
                    clients.append(self.clientManager.namedServices[stepRec['clientName']])
             
                self.steps.append(stepRec)
                
        return clients
        
    def __callbackDeferred(self, deferred, reset, result):
        """Call deferred and reset its <called> attribute so it can be called again
        
        @param deferred: deferred to be called back ('fired')
        @param reset:    True/False indicating if deferred's deferred.called attribute 
                         should be reset back to False so that it can be called again
        @param result: result to be supplied (passed) to deferred's callback method 
        """
        deferred.callback(result)
        if reset:
            deferred.called = False
        
    def _setClients(self, clients):
        """Set client instances in the <clients> list into corresponding step's 'client' data, and add workflow's  
        online and offline deferreds to that client's <extOnlineDeferreds> and <extOfflineDeferreds> dictionaries
        
        @param clients: SCSClient instances to be added to job steps's 'client' data 
        """
        for client in clients:
            for stepRec in self.steps:
                if client.name == stepRec['clientName']:
                    # Initialize client online/offline deferreds
                    onlineDeferred = defer.Deferred().addCallback(self.handleClientReconnect)
                    offlineDeferred = defer.Deferred().addCallback(self.handleClientDisconnect)
                    # Add these deferreds to corresponding client's dictionaries - to be called back when appropriate events occur
                    client.addOnlineDeferred(onlineDeferred, reset = True)
                    client.addOfflineDeferred(offlineDeferred, reset = True)
                    # Set current step record's 'client' data
                    stepRec['client'] = client
                    break
            
        # All clients have been set: check 'online' status of all clients, and set workflow's status correspondingly
        self._checkOnline() 
        
    def _setOnline(self, online):
        """Set <online> attribute
                
        If workflow's <self.online> changes from False ("offline") to True ("online"), call back 'online' 
        external deferreds (deferreds in <self.extOnlineDeferreds> dictionary). If on the other hand online  
        status changes from True ("online" to False ("offline"), call back 'offline' deferreds (deferreds
        in <self.extOfflineDeferreds> dictionary)

        @param online: True/False flag indicating if workflow is online or offline
        """
        if self.online != online:
            self.online = online
            twisted_logger.writeLog(self.logPrefix, self.logName, "Changing online status to %s" % online)
            # Call back (trigger) external deferreds
            if online:
                [self.__callbackDeferred(deferred, self.extOnlineDeferreds[deferred], online) for deferred in self.extOnlineDeferreds.keys()]
            else:
                [self.__callbackDeferred(deferred, self.extOfflineDeferreds[deferred], online) for deferred in self.extOfflineDeferreds.keys()]                
          
    def _checkOnline(self):
        "Check workflow's status (ONLINE/OFFLINE)"
        online = True

        # Re-evaluate workflow's status
        for step in self.steps:
            if step['client'] is None:
                online = False
            elif not step['client'].online:
                    online = False
            if not online:
                break
            
        if online:
            # Check that all enabled clients that belong to a given workflow have been started
            if useDB:
                # Perform SQL query to obtain a list of enabled steps
                query = "select client_name, step_no from scs.workflow_step where wf_name = '%s' and enabled = 1" % self.name
                self.db.query(query).addCallback(self._checkOnlineHandler).addErrback(self._dbFailureHandler, query)
                return None
            else:
                if len(self.steps) < len(self.info['steps']):
                    online = False
                else:
                    # Use initial <self.info> record that was used to initialize current workflow instance
                    for infoRec in self.info['steps']:
                        if infoRec['enabled']:
                            stepNo = infoRec['stepNo']
                            if not self.steps[stepNo - 1]['client']:
                                online = False
                                break
            
        self._setOnline(online)
    
    def _checkEnabled(self):
        """Check if workflow is enabled. This method should be used as a deferred's callback handler - to 
        regularly check if workflow is enabled. This is intended for allowing dynamicly enabling/disabling 
        workflow using scs.workflow_lookup table"""
        if useDB:
            # Perform SQL query to obtain a list of enabled steps            
            query = "select enabled from scs.workflow_lookup where wf_name = '%s'" % self.name
            self.db.query(query).addCallback(self._checkEnabledHandler).addErrback(self._dbFailureHandler, query)
        else:
            # Use initial <self.info> to define the value of <self.enabled>
            self.enabled = self.info['enabled']

    def _dbFailureHandler(self, fail, stmt):
        "SQL opertion failure handler"
        err_msg = "SQL Failure: %s" % fail.getErrorMessage()
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        err_msg = "SQL statement: '%s'" % stmt
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        
    def _checkOnlineHandler(self, result):
        "Set <self.online> attribute using SQL query result"
        online = True
        if len(self.steps) < len(result):
            online = False
        else:
            if result == ():
                online = False
            else:
                for (client_name, step_no) in result:
                    # Verify that given step has 'client' instance reference within <self.steps>
                    if not self.steps[step_no - 1]['client']:
                        online = False
                        break
        
        self._setOnline(online)
        
    def _checkEnabledHandler(self, result):
        "Set <self.enabled> attribute using SQL query result"
        self.enabled = (result[0][0] == True)
        
    def _scheduleCheckEnabled(self):
        "Schedule regular checks of workflow's 'enabled' status"
        if autoDiscovery:
            if not self.loop:
                # Schedule execution of itself in a loop with <checkInterval> seconds interval
                self.loop = task.LoopingCall(self._checkEnabled)
            if not self.loop.running:
                self.loop.start(checkInterval, now = False)
                    
    def enable(self):
        """Enable workflow. SCSServer entity that 'owns' this workflow will start accepting external client's 
        job requests - provided that workflow is also 'online' (all SCSClient entities used by the workflow 
        are connected to their external servers)"""
        # Schedule self._checkEnabled()
        self._scheduleCheckEnabled()
        self.enabled = True
        msg = "'%s' workflow is enabled" % self.name
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)

    def disable(self):
        "Disable workflow. SCSServer entity that 'owns' this workflow will start rejecting external client's job requests"
        # Cancel scheduled task(s)
        if self.loop and self.loop.running:
            self.loop.stop()
            
        self.enabled = False
        msg = "'%s' workflow is disabled" % self.name
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)

    def setClients(self, clientsList = None):
        "Set <self.clients> dictionary with the _SCSClientService entities"
        self.clients = {}
        if clientsList:
            for client in clientsList:
                self.clients[client.name]
                    
    def addOnlineDeferred(self, deferred, reset = True):
        "Add new external deferred to <extOnlineDeferreds> dictionary"
        self.extOnlineDeferreds[deferred] = reset
        
    def addOfflineDeferred(self, deferred, reset = True):
        "Add new external deferred to <extOfflineDeferreds> dictionary"
        self.extOfflineDeferreds[deferred] = reset        
        
    def handleClientReconnect(self, result):
        """Deferred event handler for client connect event. This method should be  
        called back by SCSClientProtocol entity in the event of connectionMade() event"""
        self._checkOnline()        

    def handleClientDisconnect(self, result):
        """Deferred event handler for client disconnect event. This method should be called back
        by SCSClientFactory entity in the event of clientConnectionLost() or clientConnectionFailed() event"""
        self._setOnline(False)
            
class _WorkflowService(service.MultiService):
    """Wraps individual workflow functionality (_Workflow) as service. 
    This class subclasses from twisted.application.service.MultiService and is responsible for
    starting/stopping individual workflows, as well as for initializing log and error files 
    associated with each _Workflow entity
    """
    def __init__(self, name, info, logName):
        """Class's constructor. Parameters:
        
        @param name:    workflow name
        @param info:    <name> - workflow name
                        <info> - dictionary containing workflow step info
                        <logDir> - log directory
        @param logName: unique log/error name (identifier) that will be used to write to these particular files        
        """
        service.MultiService.__init__(self)
        self.name = name
        self.workflowInfo = info
        
        self.workflow = None
        
        self.logName = "WorkflowManager"
        self.logPrefix = "%s SERVICE" % self.name

    def startService(self):
        "Start Workflow service"
        failPrefix = "Failure starting '%s' workflow service" % self.name

        twisted_logger.writeLog(self.logPrefix, self.logName, "Starting '%s' Workflow service..." % self.name)
        try:
            self.workflow = _Workflow(self.name, self.workflowInfo, self.logName)
        except RuntimeError, err:
            err_msg = "%s: %s" % (failPrefix, str(err))
            twisted_logger.writeLog(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err
        service.Service.startService(self)               
        
    def stopService(self):
        "Stop Workflow service"
        twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
        self.workflow.disable()
        service.Service.stopService(self)
    
class WorkflowManager(singleton.Singleton, service.MultiService):
    """Implements general SCS workflow management functionality. Implemented using Singleton design pattern 
    (extends <singleton.Singleton>) and ensures that class gets initialized only once - no matter how many 
    times constructor is called (uses @singleton.uniq() decorator for its __init() constructor
    
    Implements IResourceManager interface
    """
    implements(IResourceManager)

    @singleton.uniq
    def __init__(self, logDir = None):
        """Class's constructor
        
        @param logDir: folder where log and error files will be created
        """
        service.MultiService.__init__(self)
        self.db = TwistedMySQLdb()
        self.workflowInfo = {}
        self.name = 'WorkflowManager'

        self.logDir = logDir
        self.logName = self.name
        self.logPrefix = 'WORKFLOW_MANAGER'

    def _loadInfo(self):
        """Select workflow data from scs.workflow_lookup table
        
        @return: deferred which will 'fire' when SELECT query completes loading data
        """
        # Obtain database connection object that can be used to execute SQL query
        self.workflowInfo = {}
        query = "select wf_name, enabled, job_timeout from scs.workflow_lookup"
        return self.db.query(query).addCallback(self._loadStepInfo).addErrback(self._loadInfoFailure, query)

    def _loadStepInfo(self, result):
        """Load workflow step info from scs.workflow_step table"
        
        @return: deferred which will 'fire' when data is loaded
        """
        workflowInfo = {}
        for (wf_name, enabled, timeout) in result:
           workflowInfo[wf_name] = {'enabled': enabled == True, 'timeout': timeout}  
        
        query = "select wf_name, step_id, step_no, client_name, input, out_flag, " \
                "enabled from scs.workflow_step order by wf_name, step_no"
        
        return self.db.query(query).addCallback(self._loadComplete, workflowInfo).addErrback(self._loadInfoFailure, query)

    def _loadComplete(self, result, workflowInfo):
        "Complete loading workflowInfo data (started by self._loadInfo() and self._loadStepInfo()"
        if result == ():
            err_msg = "scs.workflow_step table contains no workflow information (empty)"
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
        
        for (wf_name, step_id, step_no, client_name, input, out_flag, enabled) in result:
            if not self.workflowInfo.has_key(wf_name):
                if not workflowInfo.has_key(wf_name):
                    err_msg = "'%s' workflow is not defined within scs.workflow_lookup table" % wf_name
                    twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
                    raise RuntimeError, err_msg
                
                self.workflowInfo.setdefault(wf_name, {'enabled': workflowInfo[wf_name]['enabled'], 
                                                       'timeout': workflowInfo[wf_name]['timeout'], 'steps': []})
                
            stepRec = {'stepID': step_id, 'stepNo': step_no, 'clientName': client_name, 
                       'inputSrc': input, 'outFlag': out_flag, 'enabled': enabled}
            self.workflowInfo[wf_name]['steps'].append(stepRec)
                            
    def _loadInfoFailure(self, fail, query):
        "Workflow load failure handler"
        err_msg = "Failure loading workflow info: %s" % fail.getErrorMessage()
        twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        twisted_logger.writeErr(self.logPrefix, self.logName, "SQL Query: '%s'" % query)
        
    def start(self, workflowName):
        """Create workflow instance <workflowName>
        
        @param workflowName: workflow name 
        @type workflowName: str
        """
        failPrefix = "Failure starting '%s' workflow service" % workflowName

        if self.namedServices.has_key(workflowName):
            if self.namedServices[workflowName].running:
                err_msg = "%s: Workflow service is already running" % failPrefix
                twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)                
                raise RuntimeError, err_msg
            else:
                # Client service has stopped: delete that service before restarting it
                self.removeService(self.getServiceNamed(workflowName))
                
        if self.workflowInfo.has_key(workflowName):
            if not self.workflowInfo[workflowName]['enabled']:
                err_msg = "%s: workflow is disabled" % failPrefix
                twisted_logger.writeErr(self.logPrefix, self.logName, err_msg) 
                raise RuntimeError, err_msg
        else:
            err_msg = "%s: unknown workflow" % failPrefix
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg) 
            raise RuntimeError, err_msg
            
        if not self.running:
            self.running = 1
            
        if self.namedServices.has_key(workflowName):
            workflowService = self.namedServices[workflowName]
            workflowService.startService()
        else:
            workflowService = _WorkflowService(workflowName, self.workflowInfo[workflowName], self.logName)
            addService(self, workflowService)
   
    def stop(self, workflowName):
        """Stop workflow service
        
        @param workflowName: workflow name
        """
        if not workflowName in self.namedServices.keys():
            err_msg = "Unable to stop '%s' workflow service: service has not been started" % workflowName
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
        
        # Remove workflow from WorkflowManager's services collection
        self.removeService(self.getServiceNamed(workflowName))
        
    def enable(self, workflowName):
        """Enable workflow. SCSServer entity that 'owns' this workflow will start accepting external client's 
        job requests - provided that workflow is also 'online' (all SCSClient entities used by the workflow 
        are connected to their external servers)"""
        if workflowName in self.namedServices.keys():            
            msg = "Enabling '%s' workflow..." % workflowName
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
            self.namedServices[workflowName].workflow.enable()
    
    def disable(self, workflowName):
        "Disable workflow. SCSServer entity that 'owns' this workflow will start rejecting external client's job requests"
        if workflowName in self.namedServices.keys():            
            msg = "Disabling '%s' workflow..." % workflowName
            twisted_logger.writeLog(self.logPrefix, self.logName, msg)
            self.namedServices[workflowName].workflow.disable()
    
    def startUp(self):
        "Start all enabled SCS workflows"
        for workflowName in self.workflowInfo.keys():
            if self.workflowInfo[workflowName]['enabled']:
                try:
                    self.start(workflowName)
                except:
                    pass
            
    def shutDown(self):
        "Stop all SCS workflows"
        for workflowName in self.namedServices.keys():
            try:
                self.stop(workflowName)
            except:
                pass

    def startService(self):
        "Start WorkflowManager service"
        actions = []
        # Initialize log and error service
        baseLogFileName = "workflow_manager"
        msg = "Opening '%s.log' and '%s.err' files in '%s' folder..." % (baseLogFileName, baseLogFileName, self.logDir)
        twisted_logger.writeLog(self.logPrefix, self.logName, msg)
        twisted_logger.initLogging(self.name, baseLogFileName, self.logDir, self)
        for srv in self.services:
            if not srv.running:
                actions.append(defer.maybeDeferred(srv.startService))
                
        twisted_logger.writeLog(self.logPrefix, self.logName, "Starting '%s' service..." % self.name)
        actions.append(defer.maybeDeferred(self.startUp))
        service.Service.startService(self)
        return defer.DeferredList(actions)
        
    def stopService(self):
        "Stop WorkflowManager service"
        twisted_logger.writeLog(self.logPrefix, self.logName, "Stopping '%s' service..." % self.name)
        deferreds = []
        for srv in self.services[:]:
            deferred = self.removeService(srv)
            if deferred:
                deferreds.append(deferred)
        
        service.Service.stopService(self)
        return defer.DeferredList(deferreds)
        
    def getResource(self, name):
        """Obtain given workflow instance
        
        @param name: workflow name
        @return: _Workflow instance
        """
        if not self.namedServices.has_key(name):
            err_msg = "'%s' workflow has not been started" % name
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
            raise RuntimeError, err_msg
                
        return self.namedServices[name].workflow

    def addOnlineDeferred(self, name, deferred, reset = True):
        "Add new external deferred to workflow's <extOnlineDeferreds> dictionary"
        if not self.namedServices.has_key(name):            
            err_msg = "addOnlineDeferred() failure: '%s' workflow entity has not been started" % name
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        else:
            self.namedServices[name].workflow.addOnlineDeferred(deferred, reset)
        
    def addOfflineDeferred(self, name, deferred, reset = True):
        "Add new external deferred to workflow's <extOfflineDeferreds> dictionary"
        if not self.namedServices.has_key(name):            
            err_msg = "addOfflineDeferred() failure: '%s' workflow entity has not been started" % name
            twisted_logger.writeErr(self.logPrefix, self.logName, err_msg)
        else:
            self.namedServices[name].workflow.addOfflineDeferred(deferred, reset)
