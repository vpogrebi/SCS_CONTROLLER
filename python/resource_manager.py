'''
Created on Aug 3, 2009

@author: valeriypogrebitskiy
'''
__docformat__ = 'epytext'

from zope.interface import Interface

class IResourceManager(Interface):
    """Defines general request interface
    
    Each class implementing IRequest interface defines functionality to verify and 
    process requests of a given (specialized) type
    Implementations: 
        - server.JobRequest, server.JobStatusRequest, 
        - client.JobRequest, client.JobStatusRequest
                         
    @ivar request: original request
    @ivar response: response data obtained in response to a given request
    @ivar scs_jobid: jobid - ID of the job to which request is related
    @ivar deferred: external deferred that will be called back when request completes successfully, or fails   
    """

    """Defines general resource manager interface
    
    Each IResourceManager object manages a list of resources of certain (specialized) type.
    Implementations: SCSServerManager, SCSClientManager, WorkflowManager
    """
    def _loadInfo():
        "Loads given resource's information from the database"
        
    def start(name):
        """Instantiates and starts one instance of a given resource type 
        
        @param name: unique instance name
        """
        
    def stop(name):
        """Stops execution of one running instance of a given resource type 
        
        @param name: unique instance name
        """
        
    def startUp():
        "Instantiates and starts all enabled instances of a given resource type"
        
    def shutDown():
        "Stops execution of all instances of a given resource type"
        
    def startService():
        "Start resource manager's service"
        
    def stopService():
        "Stop resource manager's service"

    def getResource(name):
        "Obtain given resource instance"
