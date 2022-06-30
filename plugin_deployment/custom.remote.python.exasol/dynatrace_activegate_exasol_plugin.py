'''
 Collecting System and monitoring data from Exasol's system tables:
 https://docs.exasol.com/sql_references/metadata/statistical_system_table.htm#Statistical_System_Tables
'''

from ruxit.api.base_plugin import RemoteBasePlugin
from ruxit.api.exceptions import ConfigException
import logging
import socket
import traceback
import time
import platform
import pyexasol
import ssl
import sys


logger = logging.getLogger(__name__)

### overwriting some platform functions that are used by the pyExasol library but fail on embedded python
platform.platform = lambda: "Dynatrace Active Gate Plugin"
platform.python_version = lambda: "3.8.0 (embedded)"

class MetricPoint():
    def __init__(self, key, value):
        self.key = key
        self.value = value
    
    def getArgs(self):
        return dict({'key': self.key, 'value': self.value})

class DimensionMetricPoint(MetricPoint):
    def __init__(self, key, value, dimensions):
        super().__init__(key=key, value=value)
        self.dimensions = dimensions

    def getArgs(self):
        return dict(**{'key': self.key, 'value': self.value}, **{'dimensions': self.dimensions})

class ExasolPluginRemote(RemoteBasePlugin):
    username = None
    password = None
    server = None

    def initialize(self, **kwargs):
        logger.info("Config: %s", self.config)
        self.host = self.config["host"]
        self.port = self.config["port"]
        self.username = self.config["username"]
        self.password = self.config["password"]
        self.ip = socket.gethostbyname(self.host)
        self.connectionstring = "{}:{}".format(self.ip,self.port)
        self.interval = 60

    def query(self, **kwargs):
        config = kwargs['config']
        group_name = "Exasol Database"
        group = self.topology_builder.create_group(group_name, group_name)
        device_name = self.host
        device = group.create_device(device_name, device_name)
        device.add_endpoint(ip=self.ip, port=self.port, dnsNames=[self.host])
        logger.info("Topology: group name={}, device name={}".format(group.name, device.name))
        backoff = 1
        max_retries = 2**3
        db = None
        errorMsg = ""
        #logger.info("Python Executable is: {}".format(sys.executable))
        # simple retry mechanism in case db is unreachable
        while backoff < max_retries:
            try:
                logger.info("Connecting to Exasol DB: {}".format(self.connectionstring))
                #db = Database(self.connectionstring, self.username, self.password, autocommit=True)
                db = pyexasol.connect(dsn=self.connectionstring, user=self.username, password=self.password, encryption=True, fetch_dict=True, websocket_sslopt={'cert_reqs': ssl.CERT_NONE})
                backoff = max_retries
            except Exception as error:
                #logger.error("Database offline, unreachable or wrong connection string: {}:{}".format(self.ip, self.port))
                errorMsg = str(error)
                logger.error(traceback.format_exc())
                time.sleep(backoff)
                backoff = backoff*2
        
        if backoff >= max_retries and db == None:
            device.state_metric(key="state",value="UNAVAILABLE")
            device.report_availability_event(title="Unavailable",description="Database connection unsuccessful: " + errorMsg)
        elif db:
            ### make sure we are using english notation for numbers
            sqlCommand = "ALTER SESSION SET NLS_NUMERIC_CHARACTERS='.,';"
            db.execute(sqlCommand)

            ### availability: if we can connect assume the DB is available
            device.state_metric(key="state",value="AVAILABLE")
            ### get properties
            self.getProperties(db,device)

            ### get system stats
            self.getSysStats(db,device)
            self.getNodeStats(db,device)

            ### get usage stats - users and queries
            self.getUsage(db,device)

            ### get idle sessions
            self.getIdleSessions(db,device)

            ### get time between backups
            self.getBackupInterval(db,device)

            ### get dbsizes
            self.getDBSizes(db,device)

            ### get recent events
            self.getRecentEvents(db,device)
            
            ### get SQL execution stats
            self.getSQLStats(db,device)
            
            db.close()


    def reportAbsolute(self,device,metrics):
        for measurement in metrics:
            device.absolute(**measurement.getArgs())

    def getSysStats(self,db,device):
        sqlCommand = """select LOAD, CPU, TEMP_DB_RAM, HDD_READ, HDD_WRITE, NET, SWAP, PERSISTENT_DB_RAM, MEASURE_TIME
                        from EXA_STATISTICS.EXA_MONITOR_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """.format(self.interval*2)

        resultset = db.execute(sqlCommand)
        sysstats = {}
        for result in resultset:
            logger.info(result)
            sysstats = {
                MetricPoint(key="load", value=float(result["LOAD"])),
                MetricPoint(key="cpu", value=float(result["CPU"])),
                MetricPoint(key="temp_db_ram", value=float(result["TEMP_DB_RAM"])),
                MetricPoint(key="hdd_read", value=float(result["HDD_READ"])),
                MetricPoint(key="hdd_write", value=float(result["HDD_WRITE"])),
                MetricPoint(key="net", value=float(result["NET"])),
                MetricPoint(key="swap", value=float(result["SWAP"])),
                MetricPoint(key="persistent_db_ram", value=float(result["PERSISTENT_DB_RAM"]))
            }
        
        #additionally calculate load5 and load15
        for i in [5,15]:
            sqlCommand = """select avg(LOAD) as LOAD
                            from EXA_STATISTICS.EXA_MONITOR_LAST_DAY
                            where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                            ORDER BY MEASURE_TIME DESC limit 1;
                         """.format(self.interval*i)

            resultset = db.execute(sqlCommand)
            for result in resultset:
                logger.info(result)
                sysstats.update({MetricPoint(key="load{}".format(i), value=float(result["LOAD"]))})

        if len(sysstats) > 0:
            self.reportAbsolute(device,sysstats)

    def getNodeStats(self,db,device):
        sqlCommand = "select * from EXA_LOADAVG;"
                     
        resultset = db.execute(sqlCommand)
        nodestats = {}
        for result in resultset:
            logger.info(result)
            try:
                nodestats = {
                    DimensionMetricPoint(key="node.load", value=str(result["LAST_1MIN"]), dimensions={ "Node": str(result["IPROC"]) }),
                    DimensionMetricPoint(key="node.load5", value=str(result["LAST_5MIN"]), dimensions={ "Node": str(result["IPROC"]) }),
                    DimensionMetricPoint(key="node.load15", value=str(result["LAST_15MIN"]), dimensions={ "Node": str(result["IPROC"]) })
                }
                self.reportAbsolute(device,nodestats)
            except:
                logger.warning("Key Error!")


    def getProperties(self,db,device):
        sqlCommand = """select DBMS_VERSION, NODES, DB_RAM_SIZE, CLUSTER_NAME
                        from EXA_SYSTEM_EVENTS
                        where EVENT_TYPE='STARTUP'
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """
        resultset = db.execute(sqlCommand)
        properties = {}
        for result in resultset:
            logger.info(result)
            device.report_property("Version", str(result["DBMS_VERSION"]))
            device.report_property("Cluster Nodes", str(result["NODES"]))
            device.report_property("Licensed RAM Size", "{} GB".format(result["DB_RAM_SIZE"]))
            device.report_property("Cluster Name", str(result["CLUSTER_NAME"]))


    def getRecentEvents(self,db,device):
        sqlCommand = """select EVENT_TYPE, MEASURE_TIME
                        from EXA_SYSTEM_EVENTS
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW();
                     """.format(self.interval)

        resultset = db.execute(sqlCommand)
        events = {}
        for result in resultset:
            logger.info(result)
            device.report_custom_info_event(description=str(result[0]), title=str(result["EVENT_TYPE"]), properties={'Timestamp':str(result["MEASURE_TIME"])})

    def getUsage(self,db,device):
        sqlCommand = """select USERS, QUERIES
                        from EXA_USAGE_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """.format(self.interval*2)

        resultset = db.execute(sqlCommand)
        usage = {}
        for result in resultset:
            logger.info(result)
            usage = {
                MetricPoint(key="users", value=result["USERS"]),
                MetricPoint(key="queries", value=result["QUERIES"])
            }
            self.reportAbsolute(device,usage)

    def getIdleSessions(self,db,device):
        sqlCommand = "select count(*) as count from sys.exa_all_sessions WHERE STATUS = 'IDLE';"

        resultset = db.execute(sqlCommand)
        sessions = {}
        for result in resultset:
            logger.info(result)
            sessions = {
                MetricPoint(key="sessions.idle", value=result["COUNT"])

            }
            self.reportAbsolute(device,sessions)


    def getBackupInterval(self,db,device):
        sqlCommand = "select SECONDS_BETWEEN(SYSTIMESTAMP,max(measure_time))/60/60 as backup_interval from EXA_SYSTEM_EVENTS where event_type='BACKUP_END' limit 1;"

        resultset = db.execute(sqlCommand)
        interval = {}
        for result in resultset:
            logger.info(result)
            sessions = {
                MetricPoint(key="backup.interval", value=result["BACKUP_INTERVAL"])
            }
            self.reportAbsolute(device,interval)

    def getDBSizes(self,db,device):
        # this data is only generated by exasol every 30 minutes, so we ignore any interval and just use the last value in the table
        sqlCommand = """select RAW_OBJECT_SIZE, MEM_OBJECT_SIZE, AUXILIARY_SIZE, STATISTICS_SIZE, RECOMMENDED_DB_RAM_SIZE, STORAGE_SIZE, USE, TEMP_SIZE, OBJECT_COUNT
                        from EXA_DB_SIZE_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -3600) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """

        resultset = db.execute(sqlCommand)
        usage = {}
        recommended_ram = 0
        for result in resultset:
            logger.info(result)
            usage = {
                MetricPoint(key="dbsize.raw_object_size", value=float(result["RAW_OBJECT_SIZE"]) * 1024),
                MetricPoint(key="dbsize.mem_object_size", value=float(result["MEM_OBJECT_SIZE"]) * 1024),
                MetricPoint(key="dbsize.auxiliary_size", value=float(result["AUXILIARY_SIZE"]) * 1024),
                MetricPoint(key="dbsize.statistics_size", value=float(result["STATISTICS_SIZE"]) * 1024),
                MetricPoint(key="dbsize.recommended_db_ram_size", value=float(result["RECOMMENDED_DB_RAM_SIZE"]) * 1024),
                MetricPoint(key="dbsize.storage_size", value=float(result["STORAGE_SIZE"]) * 1024),
                MetricPoint(key="dbsize.use", value=float(result["USE"])),
                MetricPoint(key="dbsize.temp_size", value=float(result["TEMP_SIZE"]) * 1024),
                MetricPoint(key="dbsize.object_count", value=int(result["OBJECT_COUNT"]))
            }
            recommended_ram = value=float(result["RECOMMENDED_DB_RAM_SIZE"]) * 1024

            self.reportAbsolute(device,usage)
        
        # also report the licensed RAM size to perform health/sizing calculation
        sqlCommand = """select DB_RAM_SIZE
                        from EXA_SYSTEM_EVENTS
                        where EVENT_TYPE='STARTUP'
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """
        resultset = db.execute(sqlCommand)
        usage = {}
        db_ram = 0
        for result in resultset:
            logger.info(result)
            db_ram = value=float(result["DB_RAM_SIZE"]) * 1024
            ram_ratio = recommended_ram/db_ram
            usage = {
                MetricPoint(key="dbsize.db_ram_size", value=float(result["DB_RAM_SIZE"]) * 1024),
                MetricPoint(key="dbsize.db_ramratio", value=float(ram_ratio))
            }
            # best practice, send out info if this is met
            if recommended_ram/2 > db_ram:
                device.report_custom_info_event(description="Actual DB RAM size is lower than half of the recommended RAM size.", title="Check DB RAM Size best practices", properties={'More Info':"https://community.exasol.com/t5/environment-management/monitoring-of-an-exasol-database/ta-p/2634#toc-hId--1644733445"})

            self.reportAbsolute(device,usage)


    # gather statistics on the execution of SQL statements
    def getSQLStats(self,db,device):
        # failed statements
        sqlCommand = """select count(EXECUTION_MODE) as count,
                               median(DURATION) as median,
                               max(DURATION) as max,
                               percentile_cont(0.9) within group (order by DURATION) as pct90,
                               COMMAND_NAME
                        from EXA_SQL_LAST_DAY
                        where SUCCESS=FALSE and START_TIME between ADD_SECONDS(NOW(), -{}) and ADD_SECONDS(NOW(), -{})
                        group by COMMAND_NAME
                        order by COMMAND_NAME;
                     """.format(self.interval*2, self.interval)

        resultset = db.execute(sqlCommand)
        successful = {}
        for result in resultset:
            logger.info(result)
            successful = {
                DimensionMetricPoint(key="db.sql_failed", value=str(result["COUNT"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) }),
                DimensionMetricPoint(key="db.sql_failed.duration_median", value=str(result["MEDIAN"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) }),
                DimensionMetricPoint(key="db.sql_failed.duration_max", value=str(result["MAX"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) }),
                DimensionMetricPoint(key="db.sql_failed.duration_pct90", value=str(result["PCT90"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) })
            }
            self.reportAbsolute(device,successful)

        # successful statements
        sqlCommand = """select count(EXECUTION_MODE) as count,
                               median(DURATION) as median,
                               max(DURATION) as max,
                               percentile_cont(0.9) within group (order by DURATION) as pct90,
                               COMMAND_NAME
                        from EXA_SQL_LAST_DAY
                        where SUCCESS=TRUE and START_TIME between ADD_SECONDS(NOW(), -{}) and ADD_SECONDS(NOW(), -{})
                        group by COMMAND_NAME
                        order by COMMAND_NAME;
                     """.format(self.interval*2, self.interval)

        resultset = db.execute(sqlCommand)
        failed = {}
        for result in resultset:
            logger.info(result)
            failed = {
                DimensionMetricPoint(key="db.sql_successful", value=str(result["COUNT"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) }),
                DimensionMetricPoint(key="db.sql_successful.duration_median", value=str(result["MEDIAN"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) }),
                DimensionMetricPoint(key="db.sql_successful.duration_max", value=str(result["MAX"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) }),
                DimensionMetricPoint(key="db.sql_successful.duration_pct90", value=str(result["PCT90"]), dimensions={ "CommandName": str(result["COMMAND_NAME"]) })
            }
            self.reportAbsolute(device,failed)
