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
from ExasolDatabaseConnector import Database
from EXASOL import OperationalError


logger = logging.getLogger(__name__)

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
        # simple retry mechanism in case db is unreachable
        while backoff < max_retries:
            try:
                logger.info("Connecting to Exasol DB: {}".format(self.connectionstring))
                db = Database(self.connectionstring, self.username, self.password, autocommit=True)
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
            sqlCommand = "ALTER SESSION SET NLS_NUMERIC_CHARACTERS='.';"
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

        result = db.execute(sqlCommand)[0]
        #logger.info(result)
        sysstats = {}
        if not None in result:
            sysstats = {
                MetricPoint(key="load", value=float(result[0])),
                MetricPoint(key="cpu", value=float(result[1])),
                MetricPoint(key="temp_db_ram", value=float(result[2])),
                MetricPoint(key="hdd_read", value=float(result[3])),
                MetricPoint(key="hdd_write", value=float(result[4])),
                MetricPoint(key="net", value=float(result[5])),
                MetricPoint(key="swap", value=float(result[6])),
                MetricPoint(key="persistent_db_ram", value=float(result[7]))
            }
        
        #additionally calculate load5 and load15
        for i in [5,15]:
            sqlCommand = """select avg(LOAD)
                            from EXA_STATISTICS.EXA_MONITOR_LAST_DAY
                            where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                            ORDER BY MEASURE_TIME DESC limit 1;
                         """.format(self.interval*i)

            result = db.execute(sqlCommand)[0]
            if not None in result:
                sysstats.update({MetricPoint(key="load{}".format(i), value=float(result[0]))})

        if len(sysstats) > 0:
            self.reportAbsolute(device,sysstats)

    def getNodeStats(self,db,device):
        sqlCommand = "select * from EXA_LOADAVG;"
                     
        resultset = db.execute(sqlCommand)
        nodestats = {}
        if len(resultset) > 0:
            #logger.info(resultset)
            for result in resultset:
                nodestats = {
                    DimensionMetricPoint(key="node.load", value=str(result[1]), dimensions={ "Node": str(result[0]) }),
                    DimensionMetricPoint(key="node.load5", value=str(result[2]), dimensions={ "Node": str(result[0]) }),
                    DimensionMetricPoint(key="node.load15", value=str(result[3]), dimensions={ "Node": str(result[0]) })
                }
                self.reportAbsolute(device,nodestats)


    def getProperties(self,db,device):
        sqlCommand = """select DBMS_VERSION, NODES, DB_RAM_SIZE, CLUSTER_NAME
                        from EXA_SYSTEM_EVENTS
                        where EVENT_TYPE='STARTUP'
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """
        result = db.execute(sqlCommand)[0]
        logger.info(result)
        properties = {}
        if not None in result:
            device.report_property("Version", str(result[0]))
            device.report_property("Cluster Nodes", str(result[1]))
            device.report_property("Licensed RAM Size", "{} GB".format(result[2]))
            device.report_property("Cluster Name", str(result[3]))


    def getRecentEvents(self,db,device):
        sqlCommand = """select EVENT_TYPE, MEASURE_TIME
                        from EXA_SYSTEM_EVENTS
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW();
                     """.format(self.interval)

        resultset = db.execute(sqlCommand)
        events = {}
        for result in resultset:
            device.report_custom_info_event(description=str(result[0]), title=str(result[0]), properties={'Timestamp':str(result[1])})

    def getUsage(self,db,device):
        sqlCommand = """select USERS, QUERIES
                        from EXA_USAGE_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """.format(self.interval*2)

        result = db.execute(sqlCommand)[0]
        #logger.info(result)
        usage = {}
        if not None in result:
            usage = {
                MetricPoint(key="users", value=result[0]),
                MetricPoint(key="queries", value=result[1])
            }
            self.reportAbsolute(device,usage)

    def getDBSizes(self,db,device):
        # this data is only generated by exasol every 30 minutes, so we ignore any interval and just use the last value in the table
        sqlCommand = """select RAW_OBJECT_SIZE, MEM_OBJECT_SIZE, AUXILIARY_SIZE, STATISTICS_SIZE, RECOMMENDED_DB_RAM_SIZE, STORAGE_SIZE, USE, TEMP_SIZE, OBJECT_COUNT
                        from EXA_DB_SIZE_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -3600) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """

        result = db.execute(sqlCommand)
        if len(result) > 0:
            result = result[0]
        #logger.info(result)
        usage = {}
        recommended_ram = 0
        if not None in result:

            usage = {
                MetricPoint(key="dbsize.raw_object_size", value=float(result[0]) * 1024),
                MetricPoint(key="dbsize.mem_object_size", value=float(result[1]) * 1024),
                MetricPoint(key="dbsize.auxiliary_size", value=float(result[2]) * 1024),
                MetricPoint(key="dbsize.statistics_size", value=float(result[3]) * 1024),
                MetricPoint(key="dbsize.recommended_db_ram_size", value=float(result[4]) * 1024),
                MetricPoint(key="dbsize.storage_size", value=float(result[5]) * 1024),
                MetricPoint(key="dbsize.use", value=float(result[6])),
                MetricPoint(key="dbsize.temp_size", value=float(result[7]) * 1024),
                MetricPoint(key="dbsize.object_count", value=int(result[8]))
            }
            recommended_ram = value=float(result[4]) * 1024

            self.reportAbsolute(device,usage)
        
        # also report the licensed RAM size to perform health/sizing calculation
        sqlCommand = """select DB_RAM_SIZE
                        from EXA_SYSTEM_EVENTS
                        where EVENT_TYPE='STARTUP'
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """
        result = db.execute(sqlCommand)
        if len(result) > 0:
            result = result[0]
        #logger.info(result)
        usage = {}
        db_ram = 0
        if not None in result:
            db_ram = value=float(result[0]) * 1024
            ram_ratio = recommended_ram/db_ram
            usage = {
                MetricPoint(key="dbsize.db_ram_size", value=float(result[0]) * 1024),
                MetricPoint(key="dbsize.db_ramratio", value=float(ram_ratio))
            }
            # best practice, send out info if this is met
            if recommended_ram/2 > db_ram:
                device.report_custom_info_event(description="Actual DB RAM size is lower than half of the recommended RAM size.", title="Check DB RAM Size best practices", properties={'More Info':"https://community.exasol.com/t5/environment-management/monitoring-of-an-exasol-database/ta-p/2634#toc-hId--1644733445"})

            self.reportAbsolute(device,usage)


    # gather statistics on the execution of SQL statements
    def getSQLStats(self,db,device):
        # failed statements
        sqlCommand = """select count(EXECUTION_MODE),
                               median(DURATION),
                               max(DURATION),
                               percentile_cont(0.9) within group (order by DURATION),
                               COMMAND_NAME
                        from EXA_SQL_LAST_DAY
                        where SUCCESS=FALSE and START_TIME between ADD_SECONDS(NOW(), -{}) and ADD_SECONDS(NOW(), -{})
                        group by COMMAND_NAME
                        order by COMMAND_NAME;
                     """.format(self.interval*2, self.interval)

        resultset = db.execute(sqlCommand)
        successful = {}
        if len(resultset) > 0:
            #logger.info(resultset)
            for result in resultset:
                successful = {
                    DimensionMetricPoint(key="db.sql_failed", value=str(result[0]), dimensions={ "CommandName": str(result[4]) }),
                    DimensionMetricPoint(key="db.sql_failed.duration_median", value=str(result[1]), dimensions={ "CommandName": str(result[4]) }),
                    DimensionMetricPoint(key="db.sql_failed.duration_max", value=str(result[2]), dimensions={ "CommandName": str(result[4]) }),
                    DimensionMetricPoint(key="db.sql_failed.duration_pct90", value=str(result[3]), dimensions={ "CommandName": str(result[4]) })
                }
                self.reportAbsolute(device,successful)

        # successful statements
        sqlCommand = """select count(EXECUTION_MODE),
                               median(DURATION),
                               max(DURATION),
                               percentile_cont(0.9) within group (order by DURATION),
                               COMMAND_NAME
                        from EXA_SQL_LAST_DAY
                        where SUCCESS=TRUE and START_TIME between ADD_SECONDS(NOW(), -{}) and ADD_SECONDS(NOW(), -{})
                        group by COMMAND_NAME
                        order by COMMAND_NAME;
                     """.format(self.interval*2, self.interval)

        resultset = db.execute(sqlCommand)
        failed = {}
        if len(resultset) > 0:
            #logger.info(resultset)
            for result in resultset:
                failed = {
                    DimensionMetricPoint(key="db.sql_successful", value=str(result[0]), dimensions={ "CommandName": str(result[4]) }),
                    DimensionMetricPoint(key="db.sql_successful.duration_median", value=str(result[1]), dimensions={ "CommandName": str(result[4]) }),
                    DimensionMetricPoint(key="db.sql_successful.duration_max", value=str(result[2]), dimensions={ "CommandName": str(result[4]) }),
                    DimensionMetricPoint(key="db.sql_successful.duration_pct90", value=str(result[3]), dimensions={ "CommandName": str(result[4]) })
                }
                self.reportAbsolute(device,failed)
