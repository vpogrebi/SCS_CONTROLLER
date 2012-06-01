'''
Created on Jul 21, 2009

@author: valeriypogrebitskiy
'''
import sys
import job
import copy
import client
import job_step
import workflow
import test_lib
import twisted_logger
import client_request
import simplejson as json

from job_step import JobStep
from twisted.trial import unittest
from twisted.python import log, failure
from deferred_lib import sleep, deferred
from twisted.protocols.basic import LineReceiver
from twisted.internet import defer, protocol, reactor


config_file = r"/Users/valeriypogrebitskiy/EclipseWorkSpace/SCS/cfg/scs_dev.cfg"
params = test_lib.getConfig(config_file)
synchdb = test_lib.getSynchDB(params)
#synchdb.conn.autocommit(True)
db = test_lib.getTwistedMySQLdb(params)

testWFName = 'DORTHY_WORKFLOW'
testInput = "I want to run a marathon"

# Set client_request.scheduleChecks to False - in order to avoid scheduling job status checks when client instantiates JobRequest
client_request.scheduleChecks = False
job.timeoutFlag = False
job_step.client.client_request.scheduleChecks = False
# Reset workflow.autoDiscovery to False - so Workflow._checkEnabled() does not interfere with test execution
workflow.autoDiscovery = False
workflow.useDB = False

log.startLogging(sys.stdout)

# Initialize workflowManager and clientManager instances
workflowManager = workflow.WorkflowManager(params['log_dir'])
clientManager = client.SCSClientManager(params['log_dir'])

failFlag = False
timeoutFlag = False

class ServerProtocol(LineReceiver):
    connDeferred = None
    disconnDeferred = None
    dataRcvdDeferred = None
    logPrefix = "TEST SERVER"
    
    def _jobSuccess(self, nothing, data):
        response = {'type': 'RESPONSE', 'scs_jobid': data['scs_jobid'], 'status': 0, 'err_msg': '', 'result_set': data['request']}
        self.sendLine(response)
        
    def _jobFailure(self, nothing, data):
        response = {'type': 'RESPONSE', 'scs_jobid': data['scs_jobid'], 'status': 1, 'err_msg': 'JOB STEP FAILED !!!'}
        self.sendLine(response)
        
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
        if data['type'] == 'REQUEST':
            twisted_logger.writeLog(self.logPrefix, None, "Server received request: %s" % data)
            if timeoutFlag:
                twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job that exceeds workflow's timeout setting...")
                # Imitate long running job on the server, and call back deferred
                sleep(None, 10).addCallback(self._jobSuccess, data)
            elif not failFlag:
                twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job on the server that succeeds...")
                # Imitate long running job on the server, and call back deferred
                sleep(None, 3).addCallback(self._jobSuccess, data)
            else:
                twisted_logger.writeLog(self.logPrefix, None, "Imitating long running job on the server that fails...")
                # Imitate long running job on the server, and call back deferred
                sleep(None, 3).addCallback(self._jobFailure, data)
        elif data['type'] == 'STATUS':
            response = {'type': 'STATUS', 'scs_jobid': data['scs_jobid'], 'status': None}
            self.sendLine(response)
            
    def sendLine(self, response):
        twisted_logger.writeLog(self.logPrefix, None, "Server sending response to the client: %s" % response)
        LineReceiver.sendLine(self, json.dumps(response))
        
class JobTest(unittest.TestCase):    
    def _startServersAndClients(self, nothing):
        "Start servers and clents"
        deferreds = []
        for clientName in clientManager.clientInfo.keys():
            port = clientManager.clientInfo[clientName]['port']
            # Start server
            self._startServer(port)
            # Start client. Since clientManager.start() returns deferred - append that deferred to connDeferreds list
            deferreds.append(self._startClient(clientName))
            
        return defer.DeferredList(deferreds).addCallback(self._startWorkflow)

    def _startServer(self, port):
        factory = protocol.ServerFactory()
        factory.protocol = ServerProtocol
        factory.protocol.dataRcvdDeferred = defer.Deferred()
        # Start server
        self.listeningPorts.append(reactor.listenTCP(port, factory))
            
    def _startClient(self, clientName):
        # Enable client
        clientManager.clientInfo[clientName]['enabled'] = True
        # Start client
        deferred = clientManager.start(clientName)
        return deferred
        
    def _startWorkflow(self, nothing):
        # Start workflow
        workflowManager.workflowInfo[testWFName]['enabled'] = True
        for stepRec in workflowManager.workflowInfo[testWFName]['steps']:
            stepRec['enabled'] = True
            
        workflowManager.start(testWFName)
        self.workflow = workflowManager.getResource(testWFName)
        # Instantiate Job instance
        self.job = job.Job(self.workflow)
    
    def _done(self, nothing):
        print "All servers are shut down"
            
    def setUp(self):
        global failFlag, timeoutFlag
        db.start()
        deferreds = []

        self.job = None
        self.logPrefix = None
        unittest.TestCase.timeout = 30
        
        failFlag = False
        timeoutFlag = False
        self.workflow = None

        # Init clientManager and workflowManager
        clientManager.clients = {}
        workflowManager.workflows = {}
        # Init listeningPorts list that will be used to stop running servers
        self.listeningPorts = []
        # Load client and server manager's info
        deferreds.append(clientManager._loadInfo())
        deferreds.append(workflowManager._loadInfo())
        return defer.DeferredList(deferreds).addCallback(self._startServersAndClients)
    
    def tearDown(self):
        deferreds = []

        # Cleanup scs.job and scs.job_step tables
        if self.job.jobID:
            stmt = "delete from scs.job_step where job_id = %d" % self.job.jobID
            synchdb.execute(stmt)                
            stmt = "delete from scs.job where job_id = %d" % self.job.jobID
            synchdb.execute(stmt)
        db.close()
        
        try:
            # Stop clients
            deferreds.append(clientManager.shutDown())
        except:
            pass
        
        # Stop workflow
        workflowManager.stop(testWFName)
        
        # Stop servers and wait for server shutdown
        for listeningPort in self.listeningPorts:
            deferreds.append(listeningPort.stopListening())

        return defer.DeferredList(deferreds).addCallback(self._done) 
    
    def test__init__(self):
        "Test that Job.__init__() constructor instantiates Job instance, without initializing JobSteps and setting <jobID>"
        self.assertEquals(self.job.db, db)
        self.assertEquals(self.job.workflow, self.workflow)
        self.assertEquals(self.job.steps, [])
        self.assertNotEquals(self.job.deferred, None)
        self.assertEquals(self.job.jobStepDeferreds, [])
        self.assertEquals(self.job.jobID, None)
        self.assertEquals(self.job.input, None)
        self.assertEquals(self.job.output, None)
        self.assertEquals(self.job.status, None)
        
    def test__init__(self):
        "Test that Job.init() initializes JobSteps, sets <jobID> and inserts scs.job record"
        self.logPrefix = "test__init__"
        
        def checkResults(result):
            twisted_logger.writeLog(self.logPrefix, None, "Checking test results...")            
            self.assertNotEquals(self.job.jobID, None)
            self.assertEquals(self.job.status, 'NEW')

            self.assertEquals(len(self.job.steps), len(self.job.workflow.steps))
            self.assertEquals(len(self.job.jobStepDeferreds), len(self.job.steps))
            for step in self.job.steps:
                self.assertEquals(isinstance(step, JobStep), True)

            # Check that there is <scs.job> record corresponding to this job
            query = "select job_id, status, wf_name, text_input, output, start_time, end_time " \
                    "from scs.job where job_id = %d" % self.job.jobID
            res = synchdb.query(query)
            print res
            self.assertEquals(len(res), 1)
            job_id, status, wf_name, text_input, output, start_time, end_time = res[0]
            self.assertEquals(job_id, self.job.jobID)
            self.assertEquals(status, self.job.status)
            self.assertEquals(text_input, None)
            self.assertEquals(output, None)
            self.assertEquals(start_time, None)
            self.assertEquals(end_time, None)
            
            # Check that there are <scs.job_step> records corresponding to all job steps
            query = "select job_id, step_id, status, text_input, output, start_time, end_time " \
                    "from scs.job_step where job_id = '%s'" % self.job.jobID
            res = synchdb.query(query)
            print res
            self.assertEquals(len(res), len(self.job.steps))
            for stepNo in range(len(res)):
                job_id, step_id, status, text_input, output, start_time, end_time = res[stepNo]
                # Check individual scs.job_step records for correctness
                self.assertEquals(job_id, self.job.jobID)
                self.assertEquals(step_id, self.job.steps[stepNo].stepID)
                self.assertEquals(status, 'NEW')
                self.assertEquals(status, self.job.steps[stepNo].status)
                self.assertEquals(text_input, None)
                self.assertEquals(output, None)
                self.assertEquals(start_time, None) 
                self.assertEquals(end_time, None) 
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeded!")
            
        return self.job.init().addCallback(checkResults)

    def test_run_SUCCESS(self):
        "Test that Job.run() starts first job step and that supplied <ext_deferred> gets called back after all steps are done"
        global failFlag
        self.logPrefix = "test_run_SUCCESS"
        unittest.TestCase.timeout = 100        
        
        def runJob(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Starting a job (Request: '%s')..." % testInput)
            ext_deferred = defer.Deferred().addCallback(extCallback)       
            self.job.run(testInput, ext_deferred)
            return ext_deferred
            
        def checkJobStepRecords(expect_status):
            twisted_logger.writeLog(self.logPrefix, None, "Checking scs.job_step results...")
            query = "select step_id, status, text_input, output, start_time, end_time from " \
                    "scs.job_step where job_id = %d" % self.job.jobID
            res = synchdb.query(query)
            for (step_id, status, text_input, output, start_time, end_time) in res:
                self.assertEquals(status, expect_status)
                self.assertNotEquals(start_time, None)
                self.assertNotEquals(end_time, None)
            
        def extCallback(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Job has completed. Checking results...")
            expect_status = 'SUCCESS'
            self.assertEquals(self.job.status, expect_status)
            # Check that job's <output> is set to last job step's output
            for step in self.job.steps:
                if step.lastStep:
                    self.assertEquals(self.job.output, step.output)
                    break
                
            query = "select status, text_input, output, start_time, end_time from scs.job where job_id = %d" % self.job.jobID
            res = synchdb.query(query)            
            status, text_input, output, start_time, end_time = res[0]
            self.assertEquals(status, expect_status)
            self.assertEquals(text_input, self.job.input)
            self.assertEquals(output, self.job.output)
            self.assertNotEquals(start_time, None)
            self.assertNotEquals(end_time, None)
            
            checkJobStepRecords(expect_status)
            twisted_logger.writeLog(self.logPrefix, None, "Test succeeeded!")
                        
        failFlag = failFlag
        return self.job.init().addCallback(runJob)

    def test_run_FAILURE(self):
        "Test that Job.run() starts first job step and that errback of the supplied <ext_deferred> gets executed when one step fails"
        global failFlag
        self.logPrefix = "test_run_FAILURE"
        
        def runJob(nothing):
            twisted_logger.writeLog(self.logPrefix, None, "Starting a job (Request: '%s')..." % testInput)
            ext_deferred = defer.Deferred().addErrback(extCallback)       
            self.job.run(testInput, ext_deferred)
            return ext_deferred
            
        def extCallback(fail):
            self.assertEquals(isinstance(fail, failure.Failure), True)
            twisted_logger.writeLog(self.logPrefix, None, "Job has failed. Checking results...")
            expect_status = 'FAILURE'
            self.assertEquals(self.job.status, expect_status)
            # Check that job's <output> is not set (job has not competed)
            self.assertEquals(self.job.output, None)
                
            query = "select status, text_input, output, start_time, end_time from scs.job where job_id = %d" % self.job.jobID
            res = synchdb.query(query)            
            status, text_input, output, start_time, end_time = res[0]
            self.assertEquals(status, expect_status)
            self.assertEquals(text_input, self.job.input)
            self.assertEquals(output, self.job.output)
            self.assertNotEquals(start_time, None)
            self.assertNotEquals(end_time, None)
            
            # Check that there are <scs.job_step> records corresponding to all job steps
            query = "select job_id, step_id, status, text_input, output, start_time, end_time " \
                    "from scs.job_step where job_id = '%s'" % self.job.jobID
            res = synchdb.query(query)
            self.assertEquals(len(res), len(self.job.steps))
            for stepNo in range(len(res)):
                job_id, step_id, status, text_input, output, start_time, end_time = res[stepNo]
                # Check individual scs.job_step records for correctness
                self.assertEquals(job_id, self.job.jobID)
                self.assertEquals(step_id, self.job.steps[stepNo].stepID)
                self.assertEquals(status, self.job.steps[stepNo].status)
                self.assertEquals(output, None)

                if stepNo == 0:
                    self.assertEquals(status, 'FAILURE')
                    self.assertEquals(text_input, testInput)
                    self.assertNotEquals(start_time, None) 
                    self.assertNotEquals(end_time, None) 
                else:
                    self.assertEquals(status, 'NEW')
                    self.assertEquals(text_input, None)
                    self.assertEquals(start_time, None) 
                    self.assertEquals(end_time, None) 

            twisted_logger.writeLog(self.logPrefix, None, "Test succeeeded!")
                        
        failFlag = True
        return self.job.init().addCallback(runJob)

    def test_run_TIMEOUT(self):
        "Test that job timeout event gets handled correctly"
        global failFlag
        self.logPrefix = "test_run_TIMEOUT"
        
        def runJob(nothing):
            global timeoutFlag
            timeoutFlag = True
            job.timeoutFlag = True
            ext_deferred = defer.Deferred().addErrback(extCallback)       
            twisted_logger.writeLog(self.logPrefix, None, "Starting a job (Request: '%s')..." % testInput)
            self.job.run(testInput, ext_deferred)
            twisted_logger.writeLog(self.logPrefix, None, "Resetting job timeout to 5 seconds")
            self.job._setTimeout(5)
            return ext_deferred
            
        def extCallback(fail):
            self.assertEquals(isinstance(fail, failure.Failure), True)
            twisted_logger.writeLog(self.logPrefix, None, "Job has failed. Checking results...")
            expect_status = 'FAILURE'
            self.assertEquals(self.job.status, expect_status)
            # Check that job's <output> is not set (job has not competed)
            self.assertEquals(self.job.output, None)
                
            query = "select status, text_input, output, start_time, end_time from scs.job where job_id = %d" % self.job.jobID
            res = synchdb.query(query)            
            status, text_input, output, start_time, end_time = res[0]
            self.assertEquals(status, expect_status)
            self.assertEquals(text_input, self.job.input)
            self.assertEquals(output, self.job.output)
            self.assertNotEquals(start_time, None)
            self.assertNotEquals(end_time, None)
            
            # Check that there are <scs.job_step> records corresponding to all job steps
            query = "select job_id, step_id, status, text_input, output, start_time, end_time " \
                    "from scs.job_step where job_id = '%s'" % self.job.jobID
            res = synchdb.query(query)
            self.assertEquals(len(res), len(self.job.steps))
            for stepNo in range(len(res)):
                job_id, step_id, status, text_input, output, start_time, end_time = res[stepNo]
                # Check individual scs.job_step records for correctness
                self.assertEquals(job_id, self.job.jobID)
                self.assertEquals(step_id, self.job.steps[stepNo].stepID)
                self.assertEquals(status, self.job.steps[stepNo].status)
                self.assertEquals(output, None)

                if stepNo == 0:
                    self.assertEquals(status, 'RUNNING') # Job step status should be 'RUNNING' - as job has timeout while given job step is still running
                    self.assertEquals(text_input, testInput)
                    self.assertNotEquals(start_time, None) 
                    self.assertEquals(end_time, None) 
                else:
                    self.assertEquals(status, 'NEW')
                    self.assertEquals(text_input, None)
                    self.assertEquals(start_time, None) 
                    self.assertEquals(end_time, None) 

            twisted_logger.writeLog(self.logPrefix, None, "Test succeeeded!")
                        
        return self.job.init().addCallback(runJob)

if __name__=="__main__":
    unittest.pyunit.main()
