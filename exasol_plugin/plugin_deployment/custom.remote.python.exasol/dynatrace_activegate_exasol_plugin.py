'''
 Collecting System and monitoring data from Exasol's system tables:
 https://docs.exasol.com/sql_references/metadata/statistical_system_table.htm#Statistical_System_Tables
'''

from ruxit.api.base_plugin import RemoteBasePlugin
from ruxit.api.exceptions import ConfigException
import logging
import socket
from ExasolDatabaseConnector import Database


logger = logging.getLogger(__name__)


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
        db = Database(self.connectionstring, self.username, self.password, autocommit=True)

        ### get properties
        deviceProperties = self.getProperties(db)
        logger.info(deviceProperties)
        for k,v in deviceProperties.items():
            device.report_property(k, v)

        ### get system stats
        self.reportData(device, self.getSysStats(db))
        self.getNodeStats(db,device)

        ### get usage stats - users and queries
        self.reportData(device, self.getUsage(db))

        ### get dbsizes
        self.reportData(device, self.getDBSizes(db))

        ### get recent events
        events = self.getRecentEvents(db)
        logger.info(events)
        for time,event in events.items():
            device.report_custom_info_event(description=event, title=event, properties={'Timestamp':time})

        self.getSQLStats(db,device)

        ### finalize, close connection
        db.close()

    def reportData(self,device,data):
        logger.info(data)
        for k,v in data.items():
            device.absolute(key=k, value=v)
    
    def reportDataWithDimensions(self,device,data):
        pass

    def getSysStats(self,db):
        sqlCommand = """select LOAD, CPU, TEMP_DB_RAM, HDD_READ, HDD_WRITE, NET, SWAP, PERSISTENT_DB_RAM, MEASURE_TIME
                        from EXA_STATISTICS.EXA_MONITOR_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """.format(self.interval*2)

        result = db.execute(sqlCommand)[0]
        #logger.info(result)
        sysstats = {}
        if not None in result:
            sysstats["load"] = float(result[0])
            sysstats["cpu"] = float(result[1])
            sysstats["temp_db_ram"] = float(result[2])
            sysstats["hdd_read"] = float(result[3])
            sysstats["hdd_write"] = float(result[4])
            sysstats["net"] = float(result[5])
            sysstats["swap"] = float(result[6])
            sysstats["persistent_db_ram"] = float(result[7])
        
        #additionally calculate load5 and load15
        for i in [5,15]:
            sqlCommand = """select avg(LOAD)
                            from EXA_STATISTICS.EXA_MONITOR_LAST_DAY
                            where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                            ORDER BY MEASURE_TIME DESC limit 1;
                         """.format(self.interval*i)

            result = db.execute(sqlCommand)[0]
            if not None in result:
                sysstats["load{}".format(i)] = float(result[0])

        return sysstats

    def getNodeStats(self,db,device):
        sqlCommand = "select * from EXA_LOADAVG;"
                     
        resultset = db.execute(sqlCommand)
        nodestats = {}
        if len(resultset) > 0:
            logger.info(resultset)
            for result in resultset:
                device.absolute(key="node.load", value=str(result[1]), dimensions={ "Node": str(result[0]) })
                device.absolute(key="node.load5", value=str(result[2]), dimensions={ "Node": str(result[0]) })
                device.absolute(key="node.load15", value=str(result[3]), dimensions={ "Node": str(result[0]) })


    def getProperties(self,db):
        sqlCommand = """select DBMS_VERSION, NODES, DB_RAM_SIZE, CLUSTER_NAME
                        from EXA_SYSTEM_EVENTS
                        where EVENT_TYPE='STARTUP'
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """
        result = db.execute(sqlCommand)[0]
        #logger.info(result)
        properties = {}
        if not None in result:
            properties["Version"] = str(result[0])
            properties["Cluster Nodes"] = str(result[1])
            properties["Licensed RAM Size"] = "{} GB".format(result[2])
            properties["Cluster Name"] = str(result[3])

        return properties

    def getRecentEvents(self,db):
        sqlCommand = """select EVENT_TYPE, MEASURE_TIME
                        from EXA_SYSTEM_EVENTS
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW();
                     """.format(self.interval)

        resultset = db.execute(sqlCommand)
        #logger.info(resultset)
        events = {}
        for result in resultset:
            events[result[1]] = str(result[0])
        
        return events

    def getUsage(self,db):
        sqlCommand = """select USERS, QUERIES
                        from EXA_USAGE_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -{}) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """.format(self.interval*2)

        result = db.execute(sqlCommand)[0]
        #logger.info(result)
        usage = {}
        if not None in result:
            usage['users'] = result[0]
            usage['queries'] = result[1]
        
        return usage

    def getDBSizes(self,db):
        # this data is only generated by exasol every 30 minutes, so we ignore any interval and just use the last value in the table
        sqlCommand = """select RAW_OBJECT_SIZE, MEM_OBJECT_SIZE, AUXILIARY_SIZE, STATISTICS_SIZE, RECOMMENDED_DB_RAM_SIZE, STORAGE_SIZE, USE, TEMP_SIZE, OBJECT_COUNT
                        from EXA_DB_SIZE_LAST_DAY
                        where MEASURE_TIME between ADD_SECONDS(NOW(), -3600) and NOW()
                        ORDER BY MEASURE_TIME DESC limit 1;
                     """

        result = db.execute(sqlCommand)[0]
        #logger.info(result)
        usage = {}
        if not None in result:
            usage['dbsize.raw_object_size'] = float(result[0]) * 1024
            usage['dbsize.mem_object_size'] = float(result[1]) * 1024
            usage['dbsize.auxiliary_size'] = float(result[2]) * 1024
            usage['dbsize.statistics_size'] = float(result[3]) * 1024
            usage['dbsize.recommended_db_ram_size'] = float(result[4]) * 1024
            usage['dbsize.storage_size'] = float(result[5]) * 1024
            usage['dbsize.use'] = float(result[6])
            usage['dbsize.temp_size'] = float(result[7]) * 1024
            usage['dbsize.object_count'] = int(result[8])
        
        return usage

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
        if len(resultset) > 0:
            logger.info(resultset)
            for result in resultset:
                device.absolute(key="db.sql_failed", value=str(result[0]), dimensions={ "CommandName": str(result[4]) })
                device.absolute(key="db.sql_failed.duration_median", value=str(result[1]), dimensions={ "CommandName": str(result[4]) })
                device.absolute(key="db.sql_failed.duration_max", value=str(result[2]), dimensions={ "CommandName": str(result[4]) })
                device.absolute(key="db.sql_failed.duration_pct90", value=str(result[3]), dimensions={ "CommandName": str(result[4]) })

        # successfult statements
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
        if len(resultset) > 0:
            logger.info(resultset)
            for result in resultset:
                device.absolute(key="db.sql_successful", value=str(result[0]), dimensions={ "CommandName": str(result[4]) })
                device.absolute(key="db.sql_successful.duration_median", value=str(result[1]), dimensions={ "CommandName": str(result[4]) })
                device.absolute(key="db.sql_successful.duration_max", value=str(result[2]), dimensions={ "CommandName": str(result[4]) })
                device.absolute(key="db.sql_successful.duration_pct90", value=str(result[3]), dimensions={ "CommandName": str(result[4]) })





        


