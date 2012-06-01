SCS Controller Deployment

1. Directory structure and file list
------------------------------------

%(eggdir)/		
	client.py
	client_request.py
	config_parser.py
	controller.py
	job.py
	job_step.py
	server.py
	workflow.py
	deferred_lib.py
	mysqldb.py
	service.py
	singleton.py
	twisted_logger.py
	request.py
	resource_manager.py
	
	cfg/
		scs_<env>.cfg
		
	doc/		
		README.txt

	test/
		controller_test.py
		test_lib.py
	
2. Dependencies
---------------

SCS Controller has following dependencies:

	- Python (2.5)
	- Python Twisted framework (Version: 8.2.0, Download URL: http://twistedmatrix.com/trac)
	- Python Zope package ‘zope.interface’ (Version: 3.3.0 - should be included with Twisted)
	- Python ‘MySQLDb’ (Version: 1.2.3c1, Download-URL: http://osdn.dl.sourceforge.net/sourceforge/mysql-python/)
	- Python ‘simplejson’ (Version: 2.0.9, Download-URL: http://pypi.python.org/packages/src/s/simplejson/simplejson-2.0.9.tar.gz) 
MySQL database (5.0)

NOTICE: To simplify SCS Controller's deployment, Python egg ('scs-<version>-py2.5.egg') is created. Using this egg automates installing system's files and all of the components it is dependent upon. To install the system using egg, run:

easy_install scs-*.egg

in the application's root directory. In addition to installing system's files in that folder, install process will also copy application's main script ('controller.py') to system's 'usr/local/bin' folder with the proper permissions


3. Environment Variables
------------------------

For SCS controller to work, following environment variables must be set:
    - $CONFIG_FILE - must point (complete path/filename) to system's configuration file (%(appdir)/cfg/scs_<env>.cfg);
    - $PYTHON_PATH - must include: 
		   a. standard Python installation locations;
		   b. Twisted framework's installation (including 'zope');
		   c. Python's 'site-packages';
		   d. SCS System source folders: %(appdir)/python, %(appdir)/python/lib, %(appdir)/python/interfaces


4. Configuration File
---------------------

System configuration file (pointed to by $CONFIG_DIR) must include 'SCS' and 'MySQL' sections ([SCS], [MySQL]). 
This configuration file is part of the Python egg distribution file (gets automatically added to <.../python2.5>/site-packages/scs-*.egg folder)
and a symlink needs to be created from /opt/scs/scs*.cfg to point to this configuration file:

viper1:/opt/scs/conf> ls -l
total 4
lrwxrwxrwx 1 root root 79 Oct  5 15:28 scs_prod.cfg -> /usr/local/lib/python2.5/site-packages/scs-0.1dev_r0-py2.5.egg/cfg/scs_prod.cfg


'SCS' section must includes following parameters: 
      - 'log_dir' - desired location of system's log files (in the directory structure outlined in section 1 - %(appdir)/log);

'MySQL' section includes database connection parameters:
      - 'server' - mysql server's hostname (required);
      - 'user' - user id (required). NOTE: this user must have read/write/delete permissions to 'scs' schema);
      - 'passwd' - user's password (required);
      - 'socket' - connection socket (optional - only if database connection requires 'socket' parameter);

Example:

[SCS]
log_dir = .../log

[MySQL]
server = blackbird.s7
user = <userid>
passwd = <password>
socket = <absolute path/name> - if needed 


5. Database Schema
------------------

SCS controller uses MySQL database for keeping system-related configuration data and storing run-time job information. Two SQL scripts are created to simplify schema creation and deletion: schema_create.sql and schema_drop.sql. Both scripts are stored in ‘scs’ SVN repository under ‘sql’ folder. 

'schema_create.sql' creates all SCS data model’s tables and populates them with system configuration data.

6. System Startup
-----------------

SCS Controller can be started either as a background (daemon) or foreground process. Background (daemon) process is preferred way to start system in production environment. In all, there are three ways to start the system:

    a. 'twistd -y controller.py' - to start the system as a background (daemon) process using 'twistd' utility. This is preferred way to start system in production;
    b. 'twistd -noy controller.py' - to start system as a foreground process using 'twistd' utility. This can be used for debugging purposes (checking by eye);
    c. 'python controller.py' - to start system as a foreground process using standard Python distribution

(a) is a preferred way of starting SCS controller in production


7. Testing
----------

To test whether application and all of its prerequisites are installed correctly (including environment variables and configuration parameters), check out '.../scs/python/test/controller_test.py' unitest script from 'scs' SVN repository, and run:

python .../controller_test.py

If requirements are satisfied and database connection works, this script should succeed
